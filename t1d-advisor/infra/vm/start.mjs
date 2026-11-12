const METADATA_URL = 'http://metadata.google.internal/computeMetadata/v1';
const SECRET_MANAGER_URL = 'https://secretmanager.googleapis.com/v1';
const SLACK_SECRET = process.env.T1D_SLACK_SECRET || 'slack-credentials';
const GEMINI_SECRET = process.env.T1D_GEMINI_SECRET || 'gemini-api-key';

/**
 * @param {string} path
 * @returns {Promise<string>}
 */
async function readMetadata(path) {
  const response = await fetch(`${METADATA_URL}/${path}`, { headers: { 'Metadata-Flavor': 'Google' } });
  if (!response.ok) {
    throw new Error(`Metadata request failed: ${path} (${response.status})`);
  }
  return response.text();
}

/**
 * @param {string} project
 * @param {string} secret
 * @param {string} accessToken
 * @returns {Promise<string>}
 */
async function accessSecret(project, secret, accessToken) {
  const response = await fetch(`${SECRET_MANAGER_URL}/projects/${project}/secrets/${secret}/versions/latest:access`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
  if (!response.ok) {
    throw new Error(`Secret Manager request failed: ${secret} (${response.status})`);
  }
  const body = await response.json();
  return Buffer.from(body.payload.data, 'base64').toString('utf8');
}

const project = await readMetadata('project/project-id');
const { access_token: accessToken } = JSON.parse(await readMetadata('instance/service-accounts/default/token'));

const slack = JSON.parse(await accessSecret(project, SLACK_SECRET, accessToken));
process.env.SLACK_BOT_TOKEN = slack.SLACK_BOT_TOKEN;
process.env.SLACK_APP_TOKEN = slack.SLACK_APP_TOKEN;
process.env.GEMINI_API_KEY = (await accessSecret(project, GEMINI_SECRET, accessToken)).trim();

await import('../../app.js');
