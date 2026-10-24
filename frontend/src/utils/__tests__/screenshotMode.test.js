import { describe, expect, it } from 'vitest';
import { HIDDEN_VALUE, redactUrls } from '../screenshotMode.js';

describe('URL masking', () => {
  it.each(['https', 'http', 'rtsp', 'rtmp', 'srt', 'udp', 'ftp', 'file'])(
    'redacts the complete %s URL, including credentials',
    (scheme) => {
      expect(
        redactUrls(
          `Failed ${scheme}://example-user:example-secret@example.invalid/path?password=secret for ExampleUser`
        )
      ).toBe(`Failed ${HIDDEN_VALUE} for ExampleUser`);
    }
  );
  it('leaves usernames and public IPs alone and masks multiple URLs', () => {
    expect(
      redactUrls(
        'ExampleUser 203.0.113.7 https://one.invalid https://two.invalid'
      )
    ).toBe(`ExampleUser 203.0.113.7 ${HIDDEN_VALUE} ${HIDDEN_VALUE}`);
  });
});
