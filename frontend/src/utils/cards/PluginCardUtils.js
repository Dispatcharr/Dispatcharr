export const getConfirmationDetails = (action, plugin, settings) => {
  const actionConfirm = action.confirm;
  const confirmField = (plugin.fields || []).find((f) => f.id === 'confirm');
  let requireConfirm = false;
  let confirmTitle = `Run ${action.label}?`;
  let confirmMessage = `You're about to run "${action.label}" from "${plugin.name}".`;

  if (actionConfirm) {
    if (typeof actionConfirm === 'boolean') {
      requireConfirm = actionConfirm;
    } else if (typeof actionConfirm === 'object') {
      requireConfirm = actionConfirm.required !== false;
      if (actionConfirm.title) confirmTitle = actionConfirm.title;
      if (actionConfirm.message) confirmMessage = actionConfirm.message;
    }
  } else if (confirmField) {
    const settingVal = settings?.confirm;
    const effectiveConfirm =
      (settingVal !== undefined ? settingVal : confirmField.default) ?? false;
    requireConfirm = !!effectiveConfirm;
  }

  return { requireConfirm, confirmTitle, confirmMessage };
};
