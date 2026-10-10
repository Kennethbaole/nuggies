import json
import threading
import unittest
from http.server import ThreadingHTTPServer
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from backend.app import Application, make_handler
from backend.live_wheel import LiveWheelTest
from backend.serial_input import ADCSample


class LiveWheelTests(unittest.TestCase):
    def test_all_directions_hover_before_return_and_do_not_reverse(self):
        for h,v,expected in [(0,3000,0),(3000,3000,1),(3000,0,2),(3000,-3000,3),(0,-3000,4),(-3000,-3000,5),(-3000,0,6),(-3000,3000,7)]:
            d=LiveWheelTest(); events=[]
            def feed(n,x,y):
                for _ in range(n):
                    slot=d.process(8192+x,8192+y)
                    if slot is not None: events.append(slot)
            feed(500,0,0);feed(75,h,v)
            self.assertEqual(d.slot,expected)
            feed(300,0,0)
            self.assertEqual(d.slot,expected)  # pulse decays during held gaze
            feed(75,-h,-v);feed(500,0,0)
            self.assertIsNone(d.slot)
            self.assertEqual(events,[expected])

    def test_clipping_and_timeout_clear_hover(self):
        d=LiveWheelTest()
        for _ in range(300):d.process(8192,8192)
        for _ in range(75):d.process(8192,11192)
        self.assertEqual(d.slot,0)
        for _ in range(2100):d.process(8192,8192)
        self.assertIsNone(d.slot)
        self.assertIsNone(d.process(16383,8192))
        self.assertEqual(d.phase,'warmup')

    def app(self):
        with patch('backend.app.load_env'),patch('backend.speech.load_env'),patch('backend.suggestions.load_env'):
            app=Application(source='serial')
        app.ingest(ADCSample(8192,8192,1000))
        return app

    def test_opt_in_stop_and_guided_mutual_exclusion(self):
        app=self.app()
        self.assertFalse(app.wheel_test)
        app.command(dict(action='wheel_test',value=True,event_id='enable'))
        self.assertTrue(app.state()['sensor_actions'])
        app.recording=True
        with self.assertRaises(ValueError):app.command(dict(action='guided_start',event_id='guided'))
        app.command(dict(action='wheel_test',value=False,event_id='stop'))
        self.assertFalse(app.state()['sensor_actions'])
        with self.assertRaises(ValueError):app.command(dict(action='wheel_test',value='yes',event_id='invalid'))
        app.connected=False
        with self.assertRaises(ValueError):app.command(dict(action='wheel_test',value=True,event_id='disconnected'))

    def test_focus_only_including_slot_zero_and_stop_prevents_future_focus(self):
        app=self.app();app.ring.action('focus',value=2)
        app.command(dict(action='wheel_test',value=True,event_id='start'))
        with patch.object(app.wheel_detector,'process',return_value=0):
            app.ingest(ADCSample(8192,8192,1004))
            self.assertEqual(app.ring.selected,0)
            self.assertEqual(app.ring.selection_id,0)
            self.assertEqual(app.ring.screen,'home')
            app.command(dict(action='wheel_test',value=False,event_id='stop'))
            app.ring.action('focus',value=2)
            app.ingest(ADCSample(8192,8192,1008))
            self.assertEqual(app.ring.selected,2)
            self.assertIsNone(app.state()['gaze_hover']['slot'])

    def test_test_selection_cannot_speak_even_after_stopping(self):
        app=self.app();app.token='';app.ring.action('select','eye-wheel-test');app.wheel_test_selections.append(app.ring.selection_id)
        server=ThreadingHTTPServer(('127.0.0.1',0),make_handler(app));thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            request=Request(f'http://127.0.0.1:{server.server_port}/api/speech',data=json.dumps({'selection_id':app.ring.selection_id,'session_id':app.session_id}).encode(),headers={'Content-Type':'application/json'})
            with patch.object(app.speech,'synthesize',side_effect=AssertionError('must not speak')):
                with self.assertRaises(HTTPError) as error:urlopen(request,timeout=3)
                self.assertEqual(error.exception.code,400)
                self.assertIn('disabled',json.load(error.exception)['error'])
                error.exception.close()
        finally:server.shutdown();server.server_close();thread.join()
