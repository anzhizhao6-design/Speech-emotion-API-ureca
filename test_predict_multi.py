"""Generated-media HTTP checks with fake inference; never load model weights."""
import asyncio
import io
import httpx
from pathlib import Path
import subprocess
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import wave
import xml.etree.ElementTree as ET

import numpy as np
from fastapi.testclient import TestClient
import app


LABELS = ['sad', 'happy', 'angry', 'neutral', 'disgusted', 'fearful', 'other', 'surprised', '<unk>']


def xml_document(segments=None):
    if segments is None:
        segments = '<SpeechSegment stime="2" dur="0.5" score="0.98" emotion="LOVE"><Word stime="2" dur=".1">A &amp; B</Word> tail</SpeechSegment><SpeechSegment stime=".5" dur=".5" score=".7" />'
    return ('<AudioDoc name="test"><ImageCaptionList><ImageSegment>image</ImageSegment></ImageCaptionList><!--keep--><?note keep?><SoundCaptionList>sound</SoundCaptionList><SegmentList>'+segments+'</SegmentList></AudioDoc>').encode()


def tree_signature(data):
    root = ET.fromstring(data, parser=ET.XMLParser(target=ET.TreeBuilder(insert_comments=True, insert_pis=True)))
    def walk(e):
        attrs = dict(e.attrib)
        if e.tag == 'SpeechSegment':
            attrs.pop('emotion', None)
        return (e.tag, attrs, e.text, e.tail, [walk(c) for c in e])
    return walk(root)


class MultiTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.temp = Path(self.folder.name)/'app-temp'
        self.temp.mkdir()
        self.patch = patch.object(app, 'TEMP_ROOT', self.temp)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.old_state = app.app.state
        state = SimpleNamespace(ffmpeg=app.executable('ffmpeg'), lock=threading.Lock(), gate=asyncio.Semaphore(1))
        self.calls = []
        owner = self
        class FakeModel:
            def generate(inner, **kwargs):
                owner.assertTrue(state.lock.locked())
                owner.assertTrue(state.gate.locked())
                owner.assertNotEqual(threading.current_thread(), threading.main_thread())
                owner.assertEqual(kwargs['input'].shape, (8000,))
                owner.assertEqual(kwargs['input'].dtype, np.float32)
                owner.calls.append(kwargs['input'].copy())
                best = '<unk>' if len(owner.calls) == 1 else 'happy'
                return [{'labels': ['prefix/'+label for label in LABELS], 'scores': [float(label == best) for label in LABELS]}]
        state.model = FakeModel()
        app.app.state = state
        self.addCleanup(setattr, app.app, 'state', self.old_state)
        self.client = TestClient(app.app, raise_server_exceptions=False)
        self.addCleanup(self.client.close)
        t = np.arange(4*48000)/48000
        signal = np.where(t<2, .2*np.sin(2*np.pi*220*t), .6*np.sin(2*np.pi*880*t))
        buffer = io.BytesIO()
        with wave.open(buffer, 'wb') as wav:
            wav.setparams((2,2,48000,0,'NONE','not compressed'))
            wav.writeframes((np.column_stack((signal,signal))*32767).astype('<i2').tobytes())
        self.audio = buffer.getvalue()

    def request(self, xml=None, audio=None):
        return self.client.post('/predict_multi', files={'file':('media.wav',self.audio if audio is None else audio),'xml':('transcript.xml',xml_document() if xml is None else xml)})

    def assert_clean(self):
        self.assertEqual(list(self.temp.iterdir()), [])

    def test_updates_preservation_order_escaping_offsets_and_one_decode(self):
        with patch.object(app.subprocess, 'run', wraps=subprocess.run) as run:
            response = self.request()
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(run.call_count, 1)
        command = run.call_args.args[0]
        self.assertEqual(command[command.index('-map')+1], '0:a:0')
        self.assertIn('charset=utf-8', response.headers['content-type'])
        self.assertIn('attachment;', response.headers['content-disposition'])
        self.assertEqual(tree_signature(xml_document()), tree_signature(response.content))
        segments = ET.fromstring(response.content).findall('./SegmentList/SpeechSegment')
        self.assertEqual([e.get('emotion') for e in segments], ['<unk>', 'happy'])
        self.assertIn(b'&lt;unk&gt;', response.content)
        # Unordered XML selects the high-amplitude interval first.
        self.assertAlmostEqual(float(np.sqrt(np.mean(self.calls[0]**2))), .6/np.sqrt(2), delta=.003)
        self.assertAlmostEqual(float(np.sqrt(np.mean(self.calls[1]**2))), .2/np.sqrt(2), delta=.003)
        self.assert_clean()

    def test_65_generated_segments_preserve_all_other_content(self):
        data = xml_document(''.join(
            '<SpeechSegment stime="'+str(2 if i%2==0 else .5)+'" dur=".5" score="'+str(i)+'" emotion="OLD"><Word>word '+str(i)+'</Word></SpeechSegment>'
            for i in range(65)))
        with patch.object(app.subprocess,'run',wraps=subprocess.run) as run:
            response = self.request(data)
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(run.call_count,1)
        self.assertEqual(len(self.calls),65)
        self.assertEqual(tree_signature(data),tree_signature(response.content))
        segments = ET.fromstring(response.content).findall('./SegmentList/SpeechSegment')
        self.assertEqual(len(segments),65)
        self.assertTrue(all(e.get('emotion') in LABELS for e in segments))
        self.assert_clean()

    def test_maximum_segment_count_and_decimal_boundaries(self):
        data = xml_document('<SpeechSegment stime="0.03" dur=".25"/>'*1000)
        root, segments = app.parse_transcript(data)
        self.assertEqual(len(segments),1000)
        self.assertEqual(segments[0][1:],(480,4480))
        self.assertEqual(len(root.findall('./SegmentList/SpeechSegment')),1000)

    def test_invalid_segments_fail_before_any_inference(self):
        for attrs in ['dur=".5"', 'stime="0"', 'stime="NaN" dur=".5"', 'stime="0" dur="Infinity"', 'stime="-1" dur=".5"', 'stime="0" dur="0"', 'stime="0" dur=".1"', 'stime="0" dur="31"', 'stime="oops" dur=".5"', 'stime="1e100000" dur=".5"']:
            with self.subTest(attrs=attrs), patch.object(app.subprocess, 'run') as run:
                response = self.request(xml_document('<SpeechSegment stime="0" dur=".5"/><SpeechSegment '+attrs+'/>'))
                self.assertEqual(response.status_code, 422, response.text)
                self.assertIn('Segment 2', response.json()['detail'])
                run.assert_not_called()
                self.assertFalse(self.calls)
                self.assert_clean()

    def test_late_out_of_range_fails_before_any_inference(self):
        for start, dur in [('3.9','.5'), ('4','.5'), ('3.5','.5001')]:
            response = self.request(xml_document('<SpeechSegment stime="0" dur=".5"/><SpeechSegment stime="'+start+'" dur="'+dur+'"/>'))
            self.assertEqual(response.status_code, 422)
            self.assertIn('Segment 2: outside', response.json()['detail'])
            self.assertFalse(self.calls)
            self.assert_clean()

    def test_xml_declarations_rejected_in_multiple_encodings(self):
        for declaration in ['<!DOCTYPE AudioDoc>', '<!DOCTYPE AudioDoc SYSTEM "file:///secret">', '<!DOCTYPE AudioDoc [<!ENTITY x "expanded">]>', '<!DOCTYPE AudioDoc [<!ENTITY x SYSTEM "http://invalid/">]>']:
            for encoding in ['utf-8','utf-16']:
                with self.subTest(encoding=encoding, declaration=declaration), patch.object(app.subprocess, 'run') as run:
                    response = self.request((declaration+xml_document().decode()).encode(encoding))
                    self.assertEqual(response.status_code, 422, response.text)
                    self.assertIn('forbidden', response.json()['detail'])
                    run.assert_not_called()
                    self.assert_clean()

    def test_malformed_wrong_structure_empty_too_many_and_deep_xml(self):
        cases = [b'', b'<bad', b'<Other/>', b'<AudioDoc/>', b'<AudioDoc><SegmentList/><SegmentList/></AudioDoc>', xml_document(''), xml_document('<Other><SpeechSegment stime="0" dur=".5"/></Other><SpeechSegment stime="0" dur=".5"/>'), xml_document('<SpeechSegment stime="0" dur=".5"/>'*1001), b'<a>'*130+b'</a>'*130]
        for data in cases:
            with self.subTest(length=len(data)), patch.object(app.subprocess, 'run') as run:
                response = self.request(data)
                self.assertEqual(response.status_code, 422, response.text)
                run.assert_not_called()
                self.assert_clean()

    def test_exactly_two_file_fields(self):
        cases = [[], [('file',('a.wav',self.audio))], [('xml',('a.xml',xml_document()))], [('file',('a.wav',self.audio)),('file',('b.wav',self.audio))], [('file',('a.wav',self.audio)),('wrong',('b.xml',xml_document()))], [('file',('a.wav',self.audio)),('xml',('b.xml',xml_document())),('extra',('c',b'x'))], [('file',('a.wav',self.audio)),('xml',(None,'text'))]]
        for files in cases:
            response = self.client.post('/predict_multi',files=files)
            self.assertIn(response.status_code, (400,422), response.text)
            self.assertFalse(self.calls)
            self.assert_clean()

    def test_upload_limits_and_extensions(self):
        for name, limit in [('MULTI_MEDIA_BYTES', len(self.audio)-1), ('MULTI_XML_BYTES', len(xml_document())-1)]:
            with patch.object(app,name,limit):
                response = self.request()
                self.assertEqual(response.status_code, 413, response.text)
                self.assert_clean()
        response = self.client.post('/predict_multi',files={'file':('a.txt',self.audio),'xml':('a.xml',xml_document())})
        self.assertEqual(response.status_code, 415)
        self.assertEqual(self.request(audio=b'').status_code, 422)
        self.assert_clean()

    def test_body_limits_are_route_specific_and_count_actual_bytes(self):
        with patch.object(app,'MAX_BODY_BYTES',100):
            self.assertEqual(self.client.post('/predict',files={'file':('a.wav',self.audio)}).status_code,413)
            self.assertEqual(self.request().status_code,200)
        with patch.object(app,'MULTI_BODY_BYTES',100):
            response = self.request()
            self.assertEqual(response.status_code,413,response.text)
        self.assert_clean()

    def test_model_failure_returns_no_partial_xml_and_cleans_up(self):
        original = app.app.state.model.generate
        def fail_second(**kwargs):
            if self.calls:
                raise RuntimeError('fake failure')
            return original(**kwargs)
        with self.assertLogs(app.log, level='ERROR'), patch.object(app.app.state.model,'generate',side_effect=fail_second):
            response = self.request()
        self.assertEqual(response.status_code,500,response.text)
        self.assertIn('Segment 2',response.json()['detail'])
        self.assertNotIn('<AudioDoc',response.text)
        self.assert_clean()

    def test_decode_failure_timeout_audio_and_output_limits(self):
        self.assertEqual(self.request(audio=b'broken').status_code,422)
        self.assert_clean()
        with patch.object(app.subprocess,'run',side_effect=subprocess.TimeoutExpired('ffmpeg',120)):
            self.assertEqual(self.request().status_code,422)
        self.assert_clean()
        with patch.object(app,'MULTI_SECONDS',3):
            response = self.request()
            self.assertEqual(response.status_code,422,response.text)
            self.assertIn('30 minutes',response.json()['detail'])
            self.assertFalse(self.calls)
        with patch.object(app,'MULTI_WAV_BYTES',100):
            self.assertEqual(self.request().status_code,422)
        with patch.object(app,'MULTI_OUTPUT_BYTES',10):
            self.assertEqual(self.request().status_code,422)
        self.assert_clean()

    def test_shared_gate_and_worker_do_not_block_event_loop(self):
        async def check():
            app.app.state.gate = asyncio.Semaphore(1)
            started = threading.Event()
            release = threading.Event()
            calls = []
            def multi_worker(*args):
                self.assertTrue(app.app.state.gate.locked())
                calls.append('multi')
                started.set()
                if not release.wait(5):
                    raise RuntimeError('test release timed out')
                return b'<AudioDoc/>'
            def single_worker(*args):
                self.assertTrue(app.app.state.gate.locked())
                calls.append('single')
                return app.Prediction(filename='a.wav',model=app.MODEL,
                                      emotion='happy',score=1,labels=LABELS,
                                      scores=[float(label=='happy') for label in LABELS])
            transport = httpx.ASGITransport(app=app.app)
            async with httpx.AsyncClient(transport=transport,base_url='http://test') as client:
                with patch.object(app,'predict_transcript',side_effect=multi_worker), patch.object(app,'convert_and_predict',side_effect=single_worker):
                    multi = asyncio.create_task(client.post('/predict_multi',files={'file':('a.wav',self.audio),'xml':('a.xml',xml_document())}))
                    single = None
                    try:
                        self.assertTrue(await asyncio.to_thread(started.wait, 5))
                        single = asyncio.create_task(client.post('/predict',files={'file':('a.wav',self.audio)}))
                        await asyncio.sleep(.05)
                        self.assertEqual(calls,['multi'])
                        self.assertFalse(single.done())
                    finally:
                        release.set()
                        responses = await asyncio.gather(*([multi,single] if single else [multi]))
                    self.assertEqual([r.status_code for r in responses],[200,200])
                    self.assertEqual(calls,['multi','single'])
        asyncio.run(check())
        self.assert_clean()

    def test_chunked_body_guard_ignores_untrusted_content_length(self):
        async def check(path, limit):
            messages = iter([{'type':'http.request','body':b'x'*6,'more_body':True},
                             {'type':'http.request','body':b'x'*6,'more_body':False}])
            sent = []
            async def receive():
                return next(messages)
            async def send(message):
                sent.append(message)
            async def consumer(scope, receive, send):
                while (await receive()).get('more_body'):
                    pass
            with patch.object(app,limit,10):
                await app.BodyLimitMiddleware(consumer)({'type':'http','path':path,'headers':[(b'content-length',b'1')]},receive,send)
            self.assertEqual(sent[0]['status'],413)
        asyncio.run(check('/predict','MAX_BODY_BYTES'))
        asyncio.run(check('/predict_multi','MULTI_BODY_BYTES'))

    def test_no_audio_video_is_rejected_and_cleaned(self):
        video = Path(self.folder.name)/'no-audio.mp4'
        subprocess.run([app.app.state.ffmpeg,'-nostdin','-v','error','-f','lavfi',
                        '-i','color=s=32x32:r=1','-t','1','-an','-c:v','mpeg4',str(video)],
                       check=True,capture_output=True,timeout=45)
        response = self.client.post('/predict_multi',files={'file':('no-audio.mp4',video.read_bytes()),'xml':('a.xml',xml_document())})
        self.assertEqual(response.status_code,422,response.text)
        self.assertFalse(self.calls)
        self.assert_clean()

    def test_non_utf8_xml_preserves_unicode_semantics(self):
        data = ('<?xml version="1.0" encoding="UTF-16"?>'+xml_document().decode().replace('image','图像')).encode('utf-16')
        response = self.request(data)
        self.assertEqual(response.status_code,200,response.text)
        self.assertIn('图像',response.content.decode('utf-8'))
        self.assertEqual(tree_signature(data),tree_signature(response.content))
        self.assert_clean()


if __name__ == '__main__':
    unittest.main()
