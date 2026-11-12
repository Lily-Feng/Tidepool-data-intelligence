import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

import { LogLevel } from '@slack/bolt';

import { resolveLogLevel } from '../../config/log-level.js';

describe('resolveLogLevel', () => {
  it('defaults to info when unset', () => {
    assert.equal(resolveLogLevel(undefined), LogLevel.INFO);
  });

  it('accepts known levels in any case', () => {
    assert.equal(resolveLogLevel('DEBUG'), LogLevel.DEBUG);
    assert.equal(resolveLogLevel(' warn '), LogLevel.WARN);
  });

  it('falls back to info for unknown values', () => {
    assert.equal(resolveLogLevel('verbose'), LogLevel.INFO);
  });
});
