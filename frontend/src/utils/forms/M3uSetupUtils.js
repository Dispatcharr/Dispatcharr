export const getM3USourceType = (account) => {
  if (!account || account.account_type === 'XC') return 'XC';
  return account.server_url || !account.file_path ? 'M3U_URL' : 'M3U_FILE';
};

export const getM3UStreamLabel = (accountType) =>
  accountType === 'STD' ? 'Streams' : 'Live TV';

export const prepareM3USourceValues = (values, sourceType) => {
  const prepared = { ...values };
  if (sourceType === 'M3U_FILE') {
    prepared.server_url = '';
  } else {
    prepared.file_path = '';
  }
  if (sourceType !== 'XC') {
    prepared.username = '';
    prepared.password = '';
  }
  return prepared;
};

export const getM3UConnectionDetails = (values, sourceType, account) => ({
  ...(account?.id ? { account_id: account.id } : {}),
  account_type: sourceType === 'XC' ? 'XC' : 'STD',
  server_url: values.server_url?.trim() || '',
  user_agent: values.user_agent === '0' ? null : values.user_agent || null,
  ...(sourceType === 'XC'
    ? {
        username: values.username?.trim() || '',
        ...(values.password ? { password: values.password } : {}),
      }
    : {}),
});

export const needsM3UConnectionCheck = (values, sourceType, account) => {
  if (sourceType === 'M3U_FILE') return false;
  if (!account?.id) return true;
  return (
    sourceType !== getM3USourceType(account) ||
    values.server_url?.trim() !== (account.server_url || '').trim() ||
    (values.user_agent === '0' ? '' : String(values.user_agent || '')) !==
      String(account.user_agent || '') ||
    (sourceType === 'XC' &&
      (values.username?.trim() !== (account.username || '').trim() ||
        !!values.password))
  );
};

export const validateNewM3UAccount = (
  values,
  file,
  {
    sourceType = values.account_type === 'XC'
      ? 'XC'
      : file
        ? 'M3U_FILE'
        : 'M3U_URL',
    existingAccount,
  } = {}
) => {
  const errors = {};
  if (!values.name?.trim()) errors.name = 'Enter an account name.';
  if (sourceType !== 'M3U_FILE' && values.server_url) {
    try {
      const url = new URL(values.server_url);
      if (!['http:', 'https:'].includes(url.protocol)) throw new Error();
    } catch {
      errors.server_url = 'Enter a complete HTTP or HTTPS URL.';
    }
  }
  if (sourceType === 'XC') {
    if (!values.server_url?.trim())
      errors.server_url = 'Enter the provider server URL.';
    if (!values.username?.trim())
      errors.username = 'Enter the provider username.';
    if (!values.password && existingAccount?.account_type !== 'XC')
      errors.password = 'Enter the provider password.';
  } else if (sourceType === 'M3U_FILE') {
    if (
      !file &&
      !(existingAccount?.account_type === 'STD' && existingAccount.file_path)
    )
      errors.file = 'Choose a playlist file.';
  } else if (!values.server_url?.trim()) {
    errors.server_url = 'Enter the playlist URL.';
  }
  return errors;
};
