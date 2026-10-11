"""Exercise actual HTTP/UI wiring with simulated EOG states, not a wearer accuracy test."""
import argparse
import json
from pathlib import Path
import threading
import time
from types import SimpleNamespace
from http.server import ThreadingHTTPServer
from unittest.mock import patch

from backend.app import Application,make_handler
from backend.serial_input import ADCSample
from backend.hud_sync import frame_for
from playwright.sync_api import sync_playwright,expect


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--profile',required=True)
    p.add_argument('--chrome');p.add_argument('--output',default='artifacts/browser-report/eog')
    args=p.parse_args();output=Path(args.output);output.mkdir(parents=True,exist_ok=True)
    with patch('backend.app.load_env'),patch('backend.speech.load_env'),patch('backend.suggestions.load_env'):
        app=Application(source='serial',eog_profile=args.profile,eog_pulse_confirmation=True,eog_return_guard=True)
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
            # Appearance checks use this isolated server; no wearer state or paid TTS.
            expect(page.locator('html')).to_have_attribute('data-theme', 'dark')
            expect(page).to_have_title('Glint')
            assert page.locator('.gesture-controls').count() == 0
            assert page.locator('.wheel-panel #listen').count() == 1
            assert page.locator('.wheel-panel #default-choices').count() == 1
            assert page.locator('.wheel-conversation').bounding_box()['y'] < page.locator('#wheel').bounding_box()['y']
            expect(page.locator('#project-tagline')).to_be_empty()
            wheel_box = page.locator('#wheel').bounding_box()
            panel_box = page.locator('.wheel-panel').bounding_box()
            assert abs(wheel_box['x'] + wheel_box['width']/2 - 720) < 2
            assert wheel_box['width'] >= 700 and panel_box['width'] >= 1300
            page.screenshot(path=str(output/'companion-dark.png'), full_page=True)
            page.click('#theme-toggle')
            expect(page.locator('html')).to_have_attribute('data-theme', 'light')
            page.reload()
            expect(page.locator('html')).to_have_attribute('data-theme', 'light')
            page.screenshot(path=str(output/'companion-light.png'), full_page=True)
            community = context.new_page()
            community.goto(f'http://127.0.0.1:{server.server_port}/community')
            expect(community.locator('html')).to_have_attribute('data-theme', 'light')
            community.click('#theme-toggle')
            expect(page.locator('html')).to_have_attribute('data-theme', 'dark')
            community.close()
            for width in (1024, 768, 390, 320):
                page.set_viewport_size({'width': width, 'height': 900})
                page.wait_for_timeout(200)  # Allow responsive compositor tiles to settle.
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), width
                expect(page.locator('#wheel')).to_be_visible()
                expect(page.locator('#default-choices')).to_be_visible()
                page.screenshot(path=str(output/f'companion-{width}.png'), full_page=width>420)
                if width<=420:
                    page.locator('#wheel').scroll_into_view_if_needed()
                    page.screenshot(path=str(output/f'wheel-{width}.png'))
                    page.evaluate('scrollTo(0, 0)')
            page.set_viewport_size({'width': 1440, 'height': 1000})
            page.click('[data-workspace="project"]')
            expect(page.locator('#project-view')).to_be_visible()
            expect(page.locator('#companion')).to_be_hidden()
            selection_before = app.ring.selection_id
            page.keyboard.press('Space')
            assert app.ring.selection_id == selection_before
            page.screenshot(path=str(output/'project-board.png'), full_page=True)
            page.click('[data-workspace="team"]')
            expect(page.locator('#team-view')).to_be_visible()
            assert page.locator('.team-card').count() == 4
            expect(page.locator('#team-view')).to_contain_text('Bella Le')
            expect(page.locator('#team-view')).to_contain_text('AJ')
            assert page.locator('.team-photo').count() == 4
            for photo in page.locator('.team-photo').all():
                photo.scroll_into_view_if_needed()
                expect(photo).to_be_visible()
                page.wait_for_function('(src) => { const img = [...document.images].find(i => i.getAttribute("src") === src); return img && img.complete && img.naturalWidth > 0; }', arg=photo.get_attribute('src'))
            page.screenshot(path=str(output/'team.png'), full_page=True)
            for width in (390, 320):
                page.set_viewport_size({'width': width, 'height': 900})
                page.wait_for_timeout(200)  # Allow responsive compositor tiles to settle.
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), width
                page.click('[data-workspace="project"]')
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), width
                page.click('[data-workspace="team"]')
            page.click('[data-workspace="wheel"]')
            page.set_viewport_size({'width': 1440, 'height': 1000})
            page.click('#wheel-focus')
            expect(page.locator('body')).to_have_class('homepage wheel-focus-open')
            page.click('#wheel-focus')
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
            expect(page.locator('body')).to_have_attribute('data-eog-cue','ready')
            # Restore stable testing choices through the actual button/API, including
            # cancelling an old pending choice without resetting the live detector.
            with app.lock:
                app.ring.set_suggestions([dict(id='mock-reply', label='Old reply', text='Old generated reply.')], 'Mock question')
                app.ring.action('focus', 'eog-communication', 6)
                app.eog_confirmation.focus(app.ring, app.wheel_detector.raw_index)
                filter_before = app.wheel_detector.filter
                raw_before = app.wheel_detector.raw_index
            expect(page.locator('#default-choices')).to_be_visible()
            page.click('#default-choices')
            expect(page.locator('[data-slot="6"]')).to_have_text('Hello')
            expect(page.locator('[data-slot="2"]')).to_have_text('Goodbye')
            expect(page.locator('[data-slot="0"]')).to_have_text('More')
            expect(page.locator('[data-slot="4"]')).to_have_text('Back')
            expect(page.locator('#heard')).to_have_text('')
            with app.lock:
                assert app.eog_confirmation.target is None
                assert app.ring.selection_id == 0
                assert app.wheel_detector.filter is filter_before
                assert app.wheel_detector.raw_index >= raw_before
                mirrored = frame_for(app.state()).split('|')
                assert mirrored[7] == 'Hello' and mirrored[3] == 'Goodbye'
            assert page.evaluate('window.__spoken.length') == 0
            # Actual UI → /api/suggest → shared wheel, with a fake reply provider.
            with patch.object(app.suggester, 'model', 'browser-test-model'), patch.object(
                    app.suggester, 'suggest', return_value=SimpleNamespace(
                        suggestions=[dict(id='test-tea', label='Tea please', text='Tea would be lovely.'),
                                     dict(id='test-water', label='Water please', text='Water instead, please.')],
                        heard='Would you like tea?', provider='ollama')):
                page.wait_for_timeout(500)  # Let the 250 ms state poll expose the mocked provider.
                expect(page.locator('#text-toggle')).to_be_enabled()
                page.click('#text-toggle')
                page.fill('#heard-input', 'Would you like tea?')
                page.click('#text-send')
                expect(page.locator('[data-slot="6"]')).to_have_text('Tea please')
                expect(page.locator('#suggest-source')).to_have_text('On-device AI reply suggestions')
                expect(page.locator('#heard')).to_contain_text('Would you like tea?')
                assert page.evaluate('window.__spoken.length') == 0
                assert app.eog_confirmation.target is None and app.ring.selection_id == 0
            with app.lock:app.eog_pipeline.paused=True
            expect(page.locator('body')).to_have_attribute('data-eog-cue','paused')
            expect(page.locator('#center-text')).to_have_text('Paused')
            with app.lock:app.eog_pipeline.paused=False
            expect(page.locator('body')).to_have_attribute('data-eog-cue','ready')
            assert all(not app.ring.slots()[i]['enabled'] for i in (1,3,5,7))
            # Starting communication is the audio gesture; speech must already be on.
            expect(page.locator('#audio-toggle')).to_have_attribute('aria-pressed','true')
            with app.lock:
                d=app.wheel_detector
                app.ring.action('focus','eog-communication',6)
                app.eog_confirmation.focus(app.ring,d.raw_index)
                app.eog_confirmation.update(app.ring,d)
            expect(page.locator('#preview-label')).to_have_text('DETECTED CHOICE · NOT YET SELECTED')
            expect(page.locator('#center-footer')).to_have_text('Ready to confirm · double blink')
            expect(page.locator('body')).to_have_attribute('data-eog-cue','confirm')
            assert page.locator('#eog-communication-status').evaluate('(el) => getComputedStyle(el).backgroundColor') == 'rgb(216, 107, 255)'
            assert page.locator('.wheel-center').evaluate('(el) => getComputedStyle(el).borderTopWidth') == '5px'
            assert page.locator('#preview-text').inner_text()==app.ring.slots()[6]['text']
            assert page.locator('.preview').bounding_box()['y'] < page.locator('#wheel').bounding_box()['y']
            page.screenshot(path=str(output/'detected-choice.png'),full_page=True)
            with app.lock:
                # Simulated event tests HTTP/render/audio dispatch, not blink accuracy.
                app.eog_confirmation.update(app.ring,d,dict(label='double_blink',reason='blink',
                    onset_sample=d.raw_index,distance=.01,other_label_margin=3,horizontal_fraction=.01,
                    source='pulse_stream',pulse_pair_valid=True,waveform_label='double_blink',direction_margin=4))
            expect(page.locator('body')).to_have_attribute('data-eog-cue','selected',timeout=3000)
            expect(page.locator('#feedback')).to_contain_text('Speaking with browser voice',timeout=5000)
            assert page.evaluate('window.__spoken.length')==1
            assert app.ring.selection_id==1
            assert page.locator('.slot.selected').count()==0
            page.screenshot(path=str(output/'communication.png'),full_page=True)
            # A recording protocol must be startable while eye control is on: it stops control first.
            page.evaluate("document.querySelector('.signal-details').open=true")
            page.select_option('#guided-protocol','vertical')
            expect(page.locator('#guided-start')).to_be_enabled()
            expect(page.locator('#guided-protocol')).to_have_value('vertical')
            page.wait_for_timeout(600)  # Cross multiple state polls: button must stay enabled.
            expect(page.locator('#guided-start')).to_be_enabled()
            page.click('#guided-start')
            expect(page.locator('#center-label')).to_have_text('GUIDED RECORDING',timeout=5000)
            assert app.guided.mode=='vertical' and app.guided.status=='running' and not app.wheel_test
            page.click('#guided-stop')
            page.click('#wheel-test-toggle')
            expect(page.locator('#wheel-test-toggle')).to_have_attribute('aria-pressed','true')
            stop.set();feeder.join(timeout=2)
            expect(page.locator('#wheel-test-status')).to_contain_text('Signal interrupted',timeout=5000)
            expect(page.locator('#eog-recenter')).to_be_disabled()
            page.screenshot(path=str(output/'disconnected.png'),full_page=True)
            page.click('#wheel-test-toggle')
            expect(page.locator('#wheel-test-status')).to_have_text('Eye wheel control off')
            expect(page.locator('#audio-toggle')).to_be_enabled()
            assert app.ring.selection_id==1
            stop.clear()
            feeder=threading.Thread(target=neutral,daemon=True);feeder.start()
            expect(page.locator('#eog-communication-toggle')).to_be_enabled()
            page.click('#eog-communication-toggle')
            expect(page.locator('#eog-communication-toggle')).to_have_attribute('aria-pressed','true')
            page.click('[data-workspace="project"]')
            expect(page.locator('#project-view')).to_be_visible()
            assert not app.eog_communication and not app.wheel_test
            page.click('[data-workspace="wheel"]')
            expect(page.locator('#companion')).to_be_visible()
            expect(page.locator('#eog-communication-toggle')).to_have_attribute('aria-pressed','false')
            assert not errors,errors
            browser.close()
        report=dict(ok=True,mode='HTTP/browser UI state simulation; not sensor accuracy',checks=[
            'project and team tabs','keyboard does not select from hidden wheel','leaving wheel stops active eye control','light and dark themes','saved theme and cross-page sync','responsive wheel at 320–1440 px','wheel full screen','opt-in','center progress','ready','retry reason','prominent status','readiness-aware cues','recenter','stale signal',
            'default choices reset without confirmation or detector reset','default choices mirrored to OLED frame','speech/text suggestions replace defaults without speaking',
            'homepage speed check','opt-in communication','four reachable positions','fixed detected-choice preview','explicit confirmation readiness','speech auto-enabled with communication','peripheral colour cues','reading pause shown','recording protocol startable from eye control','confirmed browser speech once','diagnostic speech disabled','gaze highlighting absent','HUD rendering','diagnostic mode cannot confirm','no JS errors'])
        (output/'report.json').write_text(json.dumps(report,indent=2));print(json.dumps(report))
    finally:
        stop.set();feeder.join(timeout=2);server.shutdown();server.server_close();worker.join(timeout=2)


if __name__=='__main__':main()
