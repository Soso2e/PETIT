const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../../frontend/universe-app.js'), 'utf8');
const implementation = source.slice(source.indexOf('  const detailDisplayState ='), source.indexOf('  const renderActive ='));

function harness(view = 'tasks') {
  const tasks = [{id: 1, title: '選択したタスク'}, {id: 2, external_id: 'external-2', title: '作業しているタスク'}];
  const state = {tasks, selectedTaskId: '1', activeTaskId: '1', workSession: null};
  const panel = {hidden: false, dataset: {viewPanel: view}};
  const element = () => ({dataset: {}, children: [], append(...children) {this.children.push(...children);}});
  const detailPanelEl = {...element(), replaceChildren(child) {this.children = [child];}};
  const renders = [];
  const sandbox = {
    state, panels: [panel], detailPanelEl, document: {createElement: element},
    taskKey: (task) => String(task.id), selectedTask: () => tasks.find(t => String(t.id) === state.selectedTaskId),
    text: (value, fallback) => String(value || fallback),
    renderDetail: (task) => renders.push(task.id), renderDetailEmpty: () => renders.push('selection-empty'),
  };
  vm.runInNewContext(implementation + '\nglobalThis.render = renderCurrentDetail; globalThis.display = detailDisplayState;', sandbox);
  return {...sandbox, panel, renders};
}

for (const view of ['tasks', 'chat', 'settings', 'reminders']) {
  test(`${view}: selection and stale activeTaskId cannot override the server work task`, () => {
    const h = harness(view);
    h.state.workSession = {session_id: 'work', status: 'active', task_id: 2, task: '作業しているタスク'};
    h.render();
    assert.deepEqual(h.renders, [2]);
    h.state.selectedTaskId = '1';
    h.state.workSession.elapsed_seconds = 99;
    h.render({force: false});
    assert.deepEqual(h.renders, [2], 'elapsed polling must not replace an editing form');
  });
}
test('Univ keeps its selected detail even with a different work task', () => {
  const h = harness('universe');
  h.state.workSession = {status: 'active', task_id: 2};
  h.render();
  assert.deepEqual(h.renders, [1]);
  h.panel.dataset.viewPanel = 'tasks'; h.render();
  h.panel.dataset.viewPanel = 'universe'; h.render();
  assert.deepEqual(h.renders, [1, 2, 1]);
});
test('pause preserves the task; ending clears work detail without using selection', () => {
  const h = harness();
  h.state.workSession = {status: 'paused', task_id: 'external-2'};
  h.render(); assert.deepEqual(h.renders, [2]);
  h.state.workSession.status = 'ended'; h.render({force: false});
  assert.equal(h.detailPanelEl.children[0].children[1].textContent, '作業中のタスクはありません');
  h.state.workSession = null; h.render();
  assert.equal(h.display().task, null);
});
test('free-form or unavailable work tasks show the session name without unrelated actions', () => {
  const h = harness();
  for (const task_id of [null, 'not-in-cache']) {
    h.state.workSession = {status: 'active', task_id, task: '<作業名>'};
    h.render();
    assert.equal(h.display().task, null);
    assert.equal(h.detailPanelEl.children[0].children[1].textContent, '<作業名>');
    assert.equal(h.renders.length, 0);
  }
});
