// Payload for the user API key QR code.
//
// Clients should JSON.parse the scanned text, require type === 'user_api_key'
// and a version they understand, then use api_key with base_url. The identity
// fields are advisory (for showing who the key belongs to) and may be blank.
// New fields can be added in later versions without changing the type.
export const API_KEY_QR_VERSION = 1;
export const API_KEY_QR_TYPE = 'user_api_key';

// Dense QR codes stop scanning reliably from a screen well before the format's
// hard limit (and the renderer throws when the data does not fit at all, which
// long non-ASCII names can cause). Past this many UTF-8 bytes the optional
// identity fields are blanked so the code stays scannable.
export const API_KEY_QR_MAX_BYTES = 400;

const utf8Length = (text) => new TextEncoder().encode(text).length;

export const buildUserApiKeyQrPayload = ({
  apiKey,
  baseUrl,
  username,
  firstName,
  lastName,
  email,
}) => ({
  v: API_KEY_QR_VERSION,
  type: API_KEY_QR_TYPE,
  api_key: apiKey,
  base_url: baseUrl,
  username: username || '',
  first_name: firstName || '',
  last_name: lastName || '',
  email: email || '',
});

export const buildUserApiKeyQrValue = (fields) => {
  const full = JSON.stringify(buildUserApiKeyQrPayload(fields));
  if (utf8Length(full) <= API_KEY_QR_MAX_BYTES) {
    return full;
  }

  // Keep the same shape so clients never see a different set of keys.
  return JSON.stringify(
    buildUserApiKeyQrPayload({
      apiKey: fields.apiKey,
      baseUrl: fields.baseUrl,
    })
  );
};
