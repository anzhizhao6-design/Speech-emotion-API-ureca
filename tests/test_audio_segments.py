"""Generated-media and fake-model checks; no real weights or inference."""
from pathlib import Path
import subprocess
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import wave

import numpy as np
from fastapi import HTTPException
import app


class SegmentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ffmpeg = app.executable('ffmpeg')

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.temp = self.root / 'temporary'
        self.patch = patch.object(app, 'TEMP_ROOT', self.temp)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.state = SimpleNamespace(ffmpeg=self.ffmpeg, ffprobe=app.executable('ffprobe'), lock=threading.Lock())
        self.source = self.root / 'source.wav'
        # Stereo, 48 kHz: amplitude/frequency changes identify the selected interval.
        t = np.arange(4 * 48000) / 48000
        signal = np.where(t < 2, .2 * np.sin(2*np.pi*220*t), .6 * np.sin(2*np.pi*880*t))
        self.write_wav(self.source, np.column_stack((signal, signal)), 48000)

    @staticmethod
    def write_wav(path, samples, rate):
        with wave.open(str(path), 'wb') as wav:
            wav.setparams((samples.shape[1], 2, rate, 0, 'NONE', 'not compressed'))
            wav.writeframes((samples * 32767).astype('<i2').tobytes())

    def assert_clean(self):
        self.assertEqual(list(self.temp.iterdir()), [])

    def test_accuracy_and_format(self):
        for start, frequency, amplitude in [(0.5, 220, .2), (2.25, 880, .6)]:
            with self.subTest(start=start):
                with app.extract_audio_segment(self.state, self.source, start, start + .75) as path:
                    with wave.open(str(path), 'rb') as wav:
                        self.assertEqual((wav.getnchannels(), wav.getframerate(), wav.getsampwidth(), wav.getcomptype()), (1, 16000, 2, 'NONE'))
                        self.assertEqual(wav.getnframes(), 12000)
                        samples = np.frombuffer(wav.readframes(12000), dtype='<i2') / 32768
                    expected = amplitude * np.sin(2*np.pi*frequency*(start + np.arange(12000)/16000))
                    np.testing.assert_allclose(samples[20:-20], expected[20:-20], atol=.002)
                self.assertFalse(path.exists())
        self.assert_clean()

    def test_fractional_sample_boundaries_and_exact_end(self):
        for start, end in [(1.00001, 1.50002), (3.5, 4)]:
            with app.extract_audio_segment(self.state, self.source, start, end) as path:
                with wave.open(str(path), 'rb') as wav:
                    self.assertEqual(wav.getnframes(), int(np.ceil(end*16000)-np.ceil(start*16000)))
        self.assert_clean()

    def test_invalid_timestamps(self):
        for start, end in [(-1, 1), (1, 1), (2, 1), (float('nan'), 1), (0, float('inf')), (float('-inf'), 1), ('0', 1), (None, 1), (False, 1), (0, 10**1000), (0, .1), (0, 31)]:
            with self.subTest(start=start, end=end), self.assertRaises(HTTPException) as error:
                with app.extract_audio_segment(self.state, self.source, start, end):
                    self.fail('Invalid interval accepted')
            self.assertEqual(error.exception.status_code, 422)
        self.assertFalse(self.temp.exists())

    def test_out_of_range(self):
        for start, end in [(3.5, 4.5), (5, 6), (3.5, 4.0001)]:
            with self.subTest(start=start), self.assertRaisesRegex(HTTPException, 'outside'):
                with app.extract_audio_segment(self.state, self.source, start, end):
                    self.fail('Incomplete segment accepted')
            self.assert_clean()

    def test_long_source_and_video(self):
        long_source = self.root / 'long.wav'
        self.write_wav(long_source, np.zeros((36*16000, 1)), 16000)
        for start, end in [(34, 35), (5, 35), (35, 35.25)]:
            with app.extract_audio_segment(self.state, long_source, start, end) as path:
                self.assertTrue(path.exists())
        video = self.root / 'video.mp4'
        subprocess.run([self.ffmpeg, '-nostdin', '-v', 'error', '-f', 'lavfi', '-i', 'color=s=32x32:r=1', '-i', str(self.source), '-c:v', 'mpeg4', '-c:a', 'aac', '-shortest', str(video)], check=True, capture_output=True, timeout=45)
        with app.extract_audio_segment(self.state, video, 2.25, 3) as path:
            with wave.open(str(path), 'rb') as wav:
                samples = np.frombuffer(wav.readframes(wav.getnframes()), dtype='<i2') / 32768
                self.assertEqual(wav.getnframes(), 12000)
                self.assertAlmostEqual(float(np.sqrt(np.mean(samples**2))), .6/np.sqrt(2), delta=.02)
        self.assert_clean()

    def test_missing_audio_track(self):
        video = self.root / 'silent-video.mp4'
        subprocess.run([self.ffmpeg, '-nostdin', '-v', 'error', '-f', 'lavfi',
                        '-i', 'color=s=32x32:r=1', '-t', '1', '-an',
                        '-c:v', 'mpeg4', str(video)],
                       check=True, capture_output=True, timeout=45)
        with self.assertRaises(HTTPException) as error:
            with app.extract_audio_segment(self.state, video, 0, .5):
                self.fail('Video with no audio accepted')
        self.assertEqual(error.exception.status_code, 422)
        self.assert_clean()

    def fake_model(self, output=None, failure=None):
        state = self.state
        class FakeModel:
            def generate(inner, **kwargs):
                self.assertTrue(state.lock.locked())
                self.assertEqual(kwargs['fs'], 16000)
                self.assertEqual(kwargs['granularity'], 'utterance')
                self.assertFalse(kwargs['extract_embedding'])
                self.assertEqual(kwargs['input'].dtype, np.float32)
                self.assertEqual(kwargs['input'].shape, (12000,))
                if failure:
                    raise failure
                return output
        state.model = FakeModel()

    def test_fake_model_english_alignment_and_shared_upload_path(self):
        labels = ['sad', 'happy', 'angry', 'neutral', 'disgusted', 'fearful', 'other', 'surprised', '<unk>']
        scores = [.01, .8, .02, .03, .04, .01, .02, .03, .04]
        self.fake_model([{'labels': ['prefix/' + label for label in labels], 'scores': scores}])
        result = app.predict_segment(self.state, self.source, 2.25, 3)
        self.assertEqual(result.labels, labels)
        self.assertEqual(result.scores, scores)
        self.assertEqual((result.emotion, result.score), ('happy', .8))
        self.assert_clean()
        # Existing upload conversion shares the same preprocessing/inference contract.
        with app.extract_audio_segment(self.state, self.source, 2.25, 3) as source:
            upload = app.convert_and_predict(self.state, source, self.root / 'upload.wav', 'upload.wav')
        self.assertEqual(upload.labels, result.labels)
        self.assertEqual(upload.scores, result.scores)
        self.assert_clean()

    def test_cleanup_on_inference_or_output_failure(self):
        for output, failure in [(None, RuntimeError('fake inference failed')), ([{'labels': ['bad'], 'scores': [1]}], None), ([{'labels': ['unknown']*9, 'scores': [.1]*9}], None), ([{'labels': ['happy']*9, 'scores': [float('nan')]*9}], None)]:
            self.fake_model(output, failure)
            with self.assertRaises((ValueError, RuntimeError)):
                app.predict_segment(self.state, self.source, 0, .75)
            self.assert_clean()

    def test_cleanup_on_decode_failure_timeout_and_caller_failure(self):
        damaged = self.root / 'broken.wav'
        damaged.write_bytes(b'not media')
        with self.assertRaises(HTTPException):
            with app.extract_audio_segment(self.state, damaged, 0, 1):
                self.fail('Damaged media accepted')
        self.assert_clean()
        with patch.object(app.subprocess, 'run', side_effect=subprocess.TimeoutExpired('ffmpeg', 45)):
            with self.assertRaisesRegex(HTTPException, 'timed out'):
                app.predict_segment(self.state, self.source, 0, 1)
        self.assert_clean()
        with self.assertRaisesRegex(RuntimeError, 'caller'):
            with app.extract_audio_segment(self.state, self.source, 0, 1):
                raise RuntimeError('caller failure')
        self.assert_clean()

    def test_existing_upload_duration_limits(self):
        for duration in [.1, 31]:
            source = self.root / f'{duration}.wav'
            self.write_wav(source, np.zeros((int(duration*16000), 1)), 16000)
            with self.assertRaises(HTTPException) as error:
                app.convert_and_predict(self.state, source, self.root / 'converted.wav', source.name)
            self.assertEqual(error.exception.status_code, 422)


if __name__ == '__main__':
    unittest.main()
