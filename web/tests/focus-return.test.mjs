import test from 'node:test';
import assert from 'node:assert/strict';
import { captureFocusTarget, resolveFocusTarget, mayRestoreDialogFocus } from '../focus-return.js';

test('关闭后的主动焦点优先于下一帧返回，未转移时仍恢复原控件', () => {
  const target = { tagName: 'BUTTON' },
    next = { tagName: 'INPUT' },
    inside = { tagName: 'BUTTON' };
  const dialog = { contains: (node) => node === inside };
  assert.equal(mayRestoreDialogFocus(next, target, dialog), false);
  assert.equal(mayRestoreDialogFocus({ tagName: 'BODY' }, target, dialog), true);
  assert.equal(mayRestoreDialogFocus(target, target, dialog), true);
  assert.equal(mayRestoreDialogFocus(inside, target, dialog), true);
});

function button({ id = '', action = 'script-version', version = 'v1', ...values } = {}) {
  return {
    tagName: 'BUTTON',
    id,
    name: '',
    type: 'button',
    dataset: { action, id: version },
    isConnected: true,
    disabled: false,
    hidden: false,
    closest: () => null,
    ...values,
  };
}
function resolve(target, candidates, scope = 'project-a/story') {
  return resolveFocusTarget(target, {
    originalScope: 'project-a/story',
    scope,
    candidates,
  });
}

test('正常关闭返回原触发按钮，其他同名控件不能抢走焦点', () => {
  const trigger = button();
  const target = captureFocusTarget(trigger);
  assert.equal(resolve(target, [button(), trigger]), trigger);
});

test('轮询重绘替换节点后，返回同一个历史版本而非其他版本', () => {
  const trigger = button({ isConnected: false });
  const replacement = button();
  const other = button({ version: 'v2' });
  assert.equal(resolve(captureFocusTarget(trigger), [other, replacement]), replacement);
});

test('不跨项目或页签恢复，即使旧节点仍然存在或有同名替代按钮', () => {
  const trigger = button();
  const target = captureFocusTarget(trigger);
  assert.equal(resolve(target, [trigger, button()], 'project-b/story'), null);
  assert.equal(resolve(target, [trigger], 'project-a/characters'), null);
});

test('禁用、隐藏或 inert 的控件不可作为返回目标', () => {
  const trigger = button({ isConnected: false });
  const target = captureFocusTarget(trigger);
  assert.equal(
    resolve(target, [
      button({ disabled: true }),
      button({ hidden: true }),
      button({ closest: () => ({}) }),
      button({ getClientRects: () => [] }),
    ]),
    null,
  );
});

test('表单提交打开的确认窗可在重绘后返回原表单按钮', () => {
  const form = { id: 'script-assist-form' };
  const trigger = button({
    dataset: {},
    type: 'submit',
    isConnected: false,
    closest: (selector) => (selector === 'form' ? form : null),
  });
  const replacement = button({
    dataset: {},
    type: 'submit',
    closest: (selector) => (selector === 'form' ? form : null),
  });
  const anotherForm = button({ dataset: {}, type: 'submit' });
  assert.equal(resolve(captureFocusTarget(trigger), [anotherForm, replacement]), replacement);
});

test('BODY 和没有稳定身份的已移除控件不猜测返回目标', () => {
  assert.equal(captureFocusTarget({ tagName: 'BODY' }), null);
  const trigger = button({ dataset: {}, isConnected: false });
  assert.equal(resolve(captureFocusTarget(trigger), [button({ dataset: {} })]), null);
});
