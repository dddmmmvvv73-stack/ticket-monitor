"""Playwright smoke test. Run ONLY against an isolated copy on 127.0.0.1:5051.
Creates QA records; never targets the live server. python3 tests/check_processes_ui.py
"""
from pathlib import Path
import base64
import time
from playwright.sync_api import sync_playwright

with sync_playwright() as pw:
    browser = pw.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1440, "height": 1000})
    errors = []
    page.on('pageerror', lambda e: errors.append(str(e)))
    page.goto('http://127.0.0.1:5051/proto/#wkproc', wait_until='domcontentloaded')
    page.locator('[data-proc-open="procartists"]').wait_for(timeout=60000)
    assert page.locator('[data-proc-open="procvenues"]').count() == 1
    page.locator('[data-proc-open="procartists"]').click()
    prefix = 'PW ' + str(int(time.time()))
    for suffix in ('А', 'Б', 'В'):
        page.locator('[data-proc-add] input').fill(prefix + suffix)
        page.locator('[data-proc-add] input').press('Enter')
        page.wait_for_function('title => Object.values(WK.leads).some(r => r.title === title)', arg=prefix+suffix)
    lid = page.evaluate('title => Object.keys(WK.leads).find(id => WK.leads[id].title === title)', prefix+'А')
    row = lambda key: page.locator('[data-lead-field="'+key+'"][data-id="'+lid+'"]')
    row('called').check()
    page.get_by_role('button', name='Перевести', exact=True).click()
    page.wait_for_function('id => WK.leads[id].stage === "called"', arg=lid)
    page.locator('#procQ').fill(prefix)
    page.wait_for_function('() => document.querySelectorAll(".tb-grid tbody tr").length === 3')
    page.locator('[data-proc-action="board"]').click()
    page.locator('[data-lead-drag="'+lid+'"]').drag_to(page.locator('[data-lead-drop="ready"] h3'), source_position={'x':200,'y':12})
    page.wait_for_function('id => WK.leads[id].stage === "ready"', arg=lid)
    page.locator('[data-proc-action="table"]').click()
    page.locator('#procQ').fill(prefix+'А')
    page.wait_for_function('() => document.querySelectorAll(".tb-grid tbody tr").length === 1')
    page.locator('[data-plsort="title"]').click()
    page.locator('[data-pl="cols"][data-cset="leads"]').click()
    page.locator('[data-pl-col="contact"][data-cset="leads"]').check()
    assert page.locator('[data-lead-field="contact"]').count() == 1
    page.locator('[data-pl="cols"][data-cset="leads"]').click()
    page.locator('[data-proc-action="filter"]').click()
    page.locator('[data-proc-filter="stage"]').select_option('found')
    page.wait_for_function('() => document.querySelectorAll(".tb-grid tbody tr").length === 0')
    page.locator('[data-proc-action="reset"]').click()
    page.locator('[data-proc-action="lead"][data-id="'+lid+'"]').click()
    for key,value in [('fee','300000'),('cashless','13'),('next_at','2026-11-05')]:
        page.locator('#drawer [data-lead-field="'+key+'"]').fill(value)
        page.locator('#drawer [data-lead-field="'+key+'"]').press('Tab')
        page.wait_for_function('a => String(WK.leads[a.id][a.key]) === a.value', arg={'id':lid,'key':key,'value':value})
    page.locator('#drawer [data-proc-action="pick-create"]').click()
    page.locator('#drawer [data-proc-action="pick"]').wait_for()
    page.locator('#drawer [data-proc-action="task-create"]').click()
    page.locator('#drawer [data-proc-action="task-open"]').wait_for()
    page.locator('#drawer [data-proc-action="pick"]').click()
    page.locator('.tb-wchip [data-proc-action="lead"]').wait_for()
    # Enhanced selects: change the underlying native value, as prescribed in the plan.
    city_keys = page.locator('select[data-plf$="|dec"]').evaluate_all('(els) => els.slice(0,2).map(e=>e.dataset.plf)')
    assert len(city_keys) == 2
    for key in city_keys:
        page.locator('select[data-plf="'+key+'"]').evaluate('(el)=>{el.value="yes";el.dispatchEvent(new Event("change",{bubbles:true}));}')
        page.wait_for_function('key => PLAN.lists[key.split("|")[1]].cities[key.split("|")[2]].dec === "yes"', arg=key)
    page.locator('.tb-wchip [data-proc-action="lead"]').click()
    page.locator('#drawer [data-proc-action="cities"]').click()
    page.wait_for_function('id => WK.leads[id].cities.length === 2', arg=lid)
    assert page.evaluate('id => WK.leads[id].cities.every(c=>c.at && c.city && Number.isFinite(c.price))', lid)
    page.locator('#drawer [data-proc-action="decision:next"]').click()
    page.locator('#drawer [data-proc-action="project-create"]').click()
    page.locator('#drawer [data-proc-action="project-open"]').wait_for()
    page.locator('#drawer [data-proc-action="project-open"]').click()
    page.locator('.wk-pick [data-proc-action="lead"]').click()
    page.locator('#drawer [data-proc-action="task-open"]').click()
    assert page.locator('#pjDlg [data-proc-action="lead"]').count() >= 1
    page.locator('#pjDlg [data-pj="close"]').first.click()
    page.locator('[data-proc-action="tasks"]').click()
    task = page.evaluate('id=>WK.leads[id].task', lid)
    assert page.locator('[data-wkt-open="'+task+'"]').count() >= 1
    page.locator('[data-wk-add="tasks"] input[name="text"]').fill(prefix+' задача из таблицы')
    page.locator('[data-wk-add="tasks"] input[name="text"]').press('Enter')
    page.wait_for_function('t => Object.values(WK.tasks).some(r=>r.text===t && r.proc==="procartists")', arg=prefix+' задача из таблицы')
    page.locator('[data-wkt-quickadd]').click()
    page.locator('#wkn-text').fill(prefix+' полная задача')
    page.get_by_role('button', name='Создать задачу', exact=True).click()
    page.wait_for_function('t => Object.values(WK.tasks).some(r=>r.text===t && r.proc==="procartists")', arg=prefix+' полная задача')
    page.locator('[data-wkn-new]').click()
    page.locator('[data-wkn-add="quick"]').click()
    page.locator('[data-wkn-ed-title]').fill(prefix+' заметка')
    page.locator('[data-wkn-ed-create]').click()
    page.locator('.wkn-body').fill('Заметка процесса')
    page.locator('.wkn-body').press('Enter')
    page.wait_for_function('t=>Object.values(WK.notes).some(n=>n.title===t && n.proc==="procartists" && n.body==="Заметка процесса")', arg=prefix+' заметка')
    page.locator('[data-view="wktasks"]').first.click()
    assert page.locator('[data-proc-open="procartists"]').count() >= 1
    page.reload(wait_until='domcontentloaded')
    page.wait_for_function('id=>WK_OK && WK.leads[id] && WK.leads[id].cities.length===2', arg=lid)
    assert page.evaluate('id=>WK.leads[id].stage==="decided" && WK.leads[id].season==="next"', lid)
    page.evaluate('WorkProcesses.open("procartists")')
    page.set_viewport_size({'width':390,'height':844})
    for mode in ('table','board','tasks'):
        page.locator('[data-proc-action="'+mode+'"]').click()
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1'), mode
    page.screenshot(path='/tmp/processes-mobile.png',full_page=True)
    # Creating a custom process and uploading its cover uses the same media API.
    page.locator('[data-proc-action="back"]').click()
    page.locator('[data-proc-action="new"]').click()
    page.locator('[data-proc-edit] input[name="title"]').fill(prefix+' процесс')
    image=Path('/tmp/processes-cover.png')
    image.write_bytes(base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aN3sAAAAASUVORK5CYII='))
    page.locator('[data-proc-edit] input[type="file"]').set_input_files(str(image))
    page.locator('[data-proc-edit] button').click()
    page.wait_for_function('t=>Object.values(WK.procs).some(p=>p.title===t && p.media && p.media.cover)',arg=prefix+' процесс')
    assert not errors, errors
    print('ok: table, search, columns, filter, board drag, links, cities, decision, project, tasks, notes, reload, 390px, cover')
    browser.close()
