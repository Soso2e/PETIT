'use strict';
const fs = require('node:fs');
const path = require('node:path');
const { createHash } = require('node:crypto');
const { Readable } = require('node:stream');
const { pipeline } = require('node:stream/promises');
const MAX_BYTES = 350 * 1024 * 1024;
function installerAsset(release, platform, arch) {
  const name = `PETIT-${release.tag_name.replace(/^v/, '')}-${platform === 'darwin' ? 'mac' : 'win'}-${arch}.${platform === 'darwin' ? 'dmg' : 'exe'}`;
  const asset = release.assets?.find((item) => item.name === name);
  const expected = `https://github.com/Soso2e/PETIT/releases/download/${encodeURIComponent(release.tag_name)}/${encodeURIComponent(name)}`;
  if (!asset || asset.browser_download_url !== expected || !/^sha256:[a-f0-9]{64}$/i.test(asset.digest || '') ||
      !Number.isSafeInteger(asset.size) || asset.size <= 0 || asset.size > MAX_BYTES) return null;
  return asset;
}
async function downloadVerified(asset, directory, { fetchImpl = fetch, progress = () => {} } = {}) {
  // A unique directory avoids overwriting another download or following a stale path.
  const folder = await fs.promises.mkdtemp(path.join(directory, 'petit-update-'));
  const destination = path.join(folder, path.basename(asset.name));
  try {
    const response = await fetchImpl(asset.browser_download_url, { redirect: 'follow', signal: AbortSignal.timeout(120000) });
    if (!response.ok || !response.body) throw new Error('更新のダウンロードに失敗しました。');
    const hash = createHash('sha256'); let received = 0;
    const limiter = new TransformStream({ transform(chunk, controller) {
      received += chunk.byteLength;
      if (received > asset.size || received > MAX_BYTES) throw new Error('更新ファイルのサイズが一致しません。');
      hash.update(chunk); progress(received / asset.size); controller.enqueue(chunk);
    } });
    await pipeline(Readable.fromWeb(response.body.pipeThrough(limiter)), fs.createWriteStream(destination, { flags: 'wx' }));
    if (received !== asset.size || `sha256:${hash.digest('hex')}` !== asset.digest.toLowerCase()) throw new Error('更新ファイルの検証に失敗しました。再度お試しください。');
    return destination;
  } catch (error) { await fs.promises.rm(folder, { recursive: true, force: true }); throw error; }
}
module.exports = { installerAsset, downloadVerified };
