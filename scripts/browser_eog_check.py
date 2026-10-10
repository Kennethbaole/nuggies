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
            stop.set();feeder.join(timeout=2)
            expect(page.locator('#wheel-test-status')).to_contain_text('Signal interrupted',timeout=5000)
            expect(page.locator('#eog-recenter')).to_be_disabled()
            page.screenshot(path=str(output/'disconnected.png'),full_page=True)
            page.click('#wheel-test-toggle')
            expect(page.locator('#wheel-test-status')).to_have_text('Eye wheel control off')
            expect(page.locator('#audio-toggle')).to_be_enabled()
            assert app.ring.selection_id==0
            assert not errors,errors
            browser.close()
        report=dict(ok=True,mode='HTTP/browser UI state simulation; not sensor accuracy',checks=[
            'opt-in','center progress','ready','retry reason','prominent status','readiness-aware cues','recenter','stale signal',
            'homepage speed check','speech disabled','gaze highlighting absent','HUD rendering','no automatic confirmation','no JS errors'])
        (output/'report.json').write_text(json.dumps(report,indent=2));print(json.dumps(report))
    finally:
        stop.set();feeder.join(timeout=2);server.shutdown();server.server_close();worker.join(timeout=2)


if __name__=='__main__':main()
