"""Exercise actual HTTP/UI wiring with simulated EOG states, not a wearer accuracy test."""
import argparse
import json
from pathlib import Path
import threading
import time
from http.server import ThreadingHTTPServer
from unittest.mock import patch

from backend.app import Application,make_handler
from backend.serial_input import ADCSample
from playwright.sync_api import sync_playwright,expect


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--profile',required=True)
    p.add_argument('--chrome');p.add_argument('--output',default='artifacts/browser-report/eog')
    args=p.parse_args();output=Path(args.output);output.mkdir(parents=True,exist_ok=True)
    with patch('backend.app.load_env'),patch('backend.speech.load_env'),patch('backend.suggestions.load_env'):
        app=Application(source='serial',eog_profile=args.profile)
    app.speech.api_key=''  # Never call paid speech in this simulated browser check.
    app.token='';app.recording=True # UI harness only; no simulated recording is saved.
    stop=threading.Event()
    def neutral():
        while not stop.wait(.02):
            for _ in range(5):app.ingest(ADCSample(8192,8192,time.time_ns()//1_000_000))
    feeder=threading.Thread(target=neutral,daemon=True);feeder.start()
    server=ThreadingHTTPServer(('127.0.0.1',0),make_handler(app))
    worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
    errors=[]
    try:
        with sync_playwright() as playwright:
            browser=playwright.chromium.launch(headless=True,executable_path=args.chrome)
            context=browser.new_context(viewport={'width':1440,'height':1000})
            context.add_init_script("window.__spoken=[]; window.speechSynthesis.speak = utterance => window.__spoken.push(utterance.text);")
            page=context.new_page();page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto(f'http://127.0.0.1:{server.server_port}')
            expect(page.locator('#wheel-test-toggle')).to_be_enabled()
            page.click('#wheel-test-toggle')
            expect(page.locator('#wheel-test-status')).to_contain_text('Look straight ahead')
            expect(page.locator('#eog-guidance')).to_be_visible()
            expect(page.locator('#audio-toggle')).to_be_disabled()
            expect(page.locator('#wheel-test-status')).to_contain_text('Ready.',timeout=10000)
            expect(page.locator('#center-text')).to_have_text('Ready')
            page.screenshot(path=str(output/'ready.png'),full_page=True)
            page.click('.signal-details summary')
            page.select_option('#guided-protocol','diagnostic')
            page.click('#guided-start')
            expect(page.locator('#center-label')).to_have_text('LIVE EYE SIGNAL CHECK')
            # Unit/replay tests cover detection. This intentionally injects only
            # an uncertainty state to verify its actual HTTP/browser presentation.
            with app.lock:
                app.guided.started=time.monotonic()-15 # Jump to neutral prepare, not movement input.
                app.wheel_detector._retry('blink_overlap',None,dict(label='up',distance=.03,blink_margin=1.1,direction_margin=2))
            expect(page.locator('#wheel-test-status')).to_contain_text('Look center / Retry')
            expect(page.locator('#eog-event')).to_contain_text('unknown')
            expect(page.locator('#center-text')).to_contain_text('Look center / Retry')
            assert app.guided.snapshot(time.monotonic())['paused']
            assert page.locator('.slot.selected').count()==0
            hud=context.new_page();hud.goto(f'http://127.0.0.1:{server.server_port}/hud')
            expect(hud.locator('#hud-only')).to_be_visible()
            hud.screenshot(path=str(output/'retry-hud.png'))
            page.screenshot(path=str(output/'retry.png'),full_page=True)
            page.click('#eog-recenter')
            expect(page.locator('#wheel-test-status')).to_contain_text('Look straight ahead')
            expect(page.locator('#center-text')).to_have_text('Ready',timeout=10000)
            page.click('#speed-test-start')
            expect(page.locator('#center-text')).to_have_text('Look straight ahead')
            expect(page.locator('#center-label')).to_have_text('LIVE EYE SIGNAL CHECK',timeout=10000)
            assert app.guided.mode=='speed'
            page.click('#guided-stop')
            assert app.ring.selection_id==0
            page.click('#eog-communication-toggle')
            expect(page.locator('#center-label')).to_have_text('GAZE + DOUBLE BLINK')
            expect(page.locator('#audio-toggle')).to_be_enabled()
            expect(page.locator('#eog-communication-status')).to_contain_text('Look center / Retry')
            expect(page.locator('#center-text')).to_have_text('Choose a reply',timeout=10000)
            assert all(not app.ring.slots()[i]['enabled'] for i in (1,3,5,7))
            # Starting communication is the audio gesture; speech must already be on.
            expect(page.locator('#audio-toggle')).to_have_attribute('aria-pressed','true')
            with app.lock:
                d=app.wheel_detector
                app.ring.action('focus','eog-communication',0)
                app.eog_confirmation.focus(app.ring,d.raw_index)
                app.eog_confirmation.update(app.ring,d)
            expect(page.locator('#preview-label')).to_have_text('DETECTED CHOICE · NOT YET SELECTED')
            expect(page.locator('#center-footer')).to_have_text('Ready to confirm · double blink')
            assert page.locator('#preview-text').inner_text()==app.ring.slots()[0]['text']
            assert page.locator('.preview').bounding_box()['y'] < page.locator('#wheel').bounding_box()['y']
            page.screenshot(path=str(output/'detected-choice.png'),full_page=True)
            with app.lock:
                # Simulated event tests HTTP/render/audio dispatch, not blink accuracy.
                app.eog_confirmation.update(app.ring,d,dict(label='double_blink',reason='blink',
                    onset_sample=d.raw_index,distance=.01,other_label_margin=3,horizontal_fraction=.01))
            expect(page.locator('#feedback')).to_contain_text('Speaking with browser voice',timeout=5000)
            assert page.evaluate('window.__spoken.length')==1
            assert app.ring.selection_id==1
            assert page.locator('.slot.selected').count()==0
            page.screenshot(path=str(output/'communication.png'),full_page=True)
            stop.set();feeder.join(timeout=2)
            expect(page.locator('#wheel-test-status')).to_contain_text('Signal interrupted',timeout=5000)
            expect(page.locator('#eog-recenter')).to_be_disabled()
            page.screenshot(path=str(output/'disconnected.png'),full_page=True)
            page.click('#wheel-test-toggle')
            expect(page.locator('#wheel-test-status')).to_have_text('Eye wheel control off')
            expect(page.locator('#audio-toggle')).to_be_enabled()
            assert app.ring.selection_id==1
            assert not errors,errors
            browser.close()
        report=dict(ok=True,mode='HTTP/browser UI state simulation; not sensor accuracy',checks=[
            'opt-in','center progress','ready','retry reason','prominent status','readiness-aware cues','recenter','stale signal',
            'homepage speed check','opt-in communication','four reachable positions','fixed detected-choice preview','explicit confirmation readiness','speech auto-enabled with communication','confirmed browser speech once','diagnostic speech disabled','gaze highlighting absent','HUD rendering','diagnostic mode cannot confirm','no JS errors'])
        (output/'report.json').write_text(json.dumps(report,indent=2));print(json.dumps(report))
    finally:
        stop.set();feeder.join(timeout=2);server.shutdown();server.server_close();worker.join(timeout=2)


if __name__=='__main__':main()
