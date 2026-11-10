import { OpenAIChatCompletionsModel, setTracingDisabled } from '@openai/agents';
import OpenAI from 'openai';

const GEMINI_OPENAI_BASE_URL = 'https://generativelanguage.googleapis.com/v1beta/openai/';
const DEFAULT_GEMINI_MODEL = 'gemini-3.5-flash-lite';

setTracingDisabled(true);

/** @type {OpenAIChatCompletionsModel | undefined} */
let cachedModel;

/**
 * Gemini, reached through its OpenAI-compatible endpoint.
 * @returns {OpenAIChatCompletionsModel}
 */
export function geminiModel() {
  if (!cachedModel) {
    const apiKey = process.env.GEMINI_API_KEY;
    if (!apiKey) {
      throw new Error('GEMINI_API_KEY is not set. Add it to .env (never commit it).');
    }
    const client = new OpenAI({ apiKey, baseURL: GEMINI_OPENAI_BASE_URL });
    cachedModel = new OpenAIChatCompletionsModel(client, process.env.GEMINI_MODEL || DEFAULT_GEMINI_MODEL);
  }
  return cachedModel;
}
