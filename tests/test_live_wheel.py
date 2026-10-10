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
    def test_four_direction_mapping_and_no_return_duplicate(self):
        for channel, sign, expected in [('h',-1,'left'),('h',1,'right'),('v',1,'select'),('v',-1,'back')]:
            detector=LiveWheelTest();actions=[]
            for duration,offset in [(2,0),(.3,sign*3000),(1.2,0),(.3,-sign*3000),(2,0)]:
                for _ in range(round(duration*250)):
                    action=detector.process(8192+(offset if channel=='h' else 0),8192+(offset if channel=='v' else 0))
                    if action:actions.append(action)
            self.assertEqual(actions,[expected])

    def test_simultaneous_axes_and_clipping_apply_no_action(self):
        d=LiveWheelTest()
        with patch.object(d.horizontal,'process',return_value=[object()]),patch.object(d.vertical,'process',return_value=[object()]):
            self.assertIsNone(d.process(8192,8192))
        self.assertIsNone(d.process(16383,8192))

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

    def test_selection_is_tagged_and_stop_prevents_future_actions(self):
        app=self.app();app.command(dict(action='wheel_test',value=True,event_id='start'))
        with patch.object(app.wheel_detector,'process',return_value='select'):
            app.ingest(ADCSample(8192,8192,1004))
            self.assertEqual(app.ring.selection_id,1)
            self.assertIn(1,app.wheel_test_selections)
            app.command(dict(action='wheel_test',value=False,event_id='stop'))
            app.ingest(ADCSample(8192,8192,1008))
            self.assertEqual(app.ring.selection_id,1)

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
