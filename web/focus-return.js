/** 弹窗返回焦点的快照：只记录控件身份，不缓存用户输入或页面数据。 */
const ACTION_KEYS = ['action', 'id', 'tab', 'view', 'stage', 'kind', 'filter'];

/** 下一帧恢复前尊重已主动移到的新控件，避免关闭回调抢走后续键盘操作。 */
export function mayRestoreDialogFocus(active, target, dialog) {
  return (
    !active ||
    ['BODY', 'HTML'].includes(active.tagName) ||
    dialog?.contains(active) ||
    active === target
  );
}

export function captureFocusTarget(element) {
  if (!element || ['BODY', 'HTML'].includes(element.tagName)) return null;
  return {
    element,
    id: element.id || '',
    tag: element.tagName,
    name: element.name || '',
    type: element.type || '',
    formId: element.closest?.('form')?.id || '',
    action: Object.fromEntries(
      ACTION_KEYS.filter((key) => element.dataset?.[key] !== undefined).map((key) => [
        key,
        element.dataset[key],
      ]),
    ),
  };
}

function available(element) {
  return !!(
    element?.isConnected &&
    !element.disabled &&
    !element.hidden &&
    !element.closest?.('[hidden], [inert]') &&
    // CSS隐藏（如专注模式收起的侧栏）同样不能接收恢复焦点。
    (!element.getClientRects || element.getClientRects().length > 0)
  );
}

/** 页面重绘会替换原节点；只在原项目/连接/页签仍相同时寻找语义相同的控件。 */
export function resolveFocusTarget(target, { scope, originalScope, candidates = [] }) {
  if (!target || scope !== originalScope) return null;
  if (available(target.element)) return target.element;
  const hasIdentity = target.id || Object.keys(target.action).length || target.formId;
  if (!hasIdentity) return null;
  return (
    [...candidates].find(
      (candidate) =>
        available(candidate) &&
        candidate.tagName === target.tag &&
        (target.id
          ? candidate.id === target.id
          : (candidate.name || '') === target.name &&
            (candidate.type || '') === target.type &&
            (candidate.closest?.('form')?.id || '') === target.formId &&
            Object.entries(target.action).every(
              ([key, value]) => candidate.dataset?.[key] === value,
            )),
    ) || null
  );
}
