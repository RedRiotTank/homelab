const http = require('http');
const fs = require('fs');
const path = require('path');

const BASE_DIR = '/themes';
const PORT = 3000;

const MIME_TYPES = {
  '.html': 'text/html',
  '.css': 'text/css',
  '.js': 'application/javascript',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.gif': 'image/gif',
  '.svg': 'image/svg+xml',
  '.json': 'application/json'
};

function getThemes(type) {
  const dir = path.join(BASE_DIR, type);
  if (!fs.existsSync(dir)) return [];
  return fs.readdirSync(dir, { withFileTypes: true })
    .filter(dirent => dirent.isDirectory() && !dirent.name.startsWith('.'))
    .map(dirent => dirent.name);
}

function loadConfig(type) {
  const dir = path.join(BASE_DIR, type);
  const configFile = path.join(dir, 'themes.json');
  const available = getThemes(type);
  let config = {};

  if (fs.existsSync(configFile)) {
    try {
      config = JSON.parse(fs.readFileSync(configFile, 'utf8'));
    } catch (e) {
      config = {};
    }
  }

  available.forEach(theme => {
    if (config[theme] === undefined) config[theme] = true;
  });

  return config;
}

function saveConfig(type, config) {
  const configFile = path.join(BASE_DIR, type, 'themes.json');
  fs.writeFileSync(configFile, JSON.stringify(config, null, 2));
}

const server = http.createServer((req, res) => {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');

  if (req.method === 'OPTIONS') {
    res.writeHead(204);
    return res.end();
  }

  // API: Get themes for a specific type (403 or 404)
  if (req.method === 'GET' && req.url.startsWith('/api/themes/')) {
    const type = req.url.split('/')[3];
    if (type !== '403' && type !== '404') {
      res.writeHead(400);
      return res.end('Invalid error code');
    }
    const config = loadConfig(type);
    res.writeHead(200, { 'Content-Type': 'application/json' });
    return res.end(JSON.stringify(config));
  }

  // API: Toggle theme
  if (req.method === 'POST' && req.url === '/api/toggle') {
    let body = '';
    req.on('data', chunk => { body += chunk; });
    req.on('end', () => {
      try {
        const { type, theme, enabled } = JSON.parse(body);
        if (type !== '403' && type !== '404') {
          res.writeHead(400, { 'Content-Type': 'application/json' });
          return res.end(JSON.stringify({ error: 'Invalid type' }));
        }
        const config = loadConfig(type);
        if (config[theme] !== undefined) {
          config[theme] = !!enabled;
          saveConfig(type, config);
          res.writeHead(200, { 'Content-Type': 'application/json' });
          return res.end(JSON.stringify({ success: true, config }));
        }
        res.writeHead(404, { 'Content-Type': 'application/json' });
        return res.end(JSON.stringify({ error: 'Theme not found' }));
      } catch (e) {
        res.writeHead(400, { 'Content-Type': 'application/json' });
        return res.end(JSON.stringify({ error: 'Invalid payload' }));
      }
    });
    return;
  }

  // Static Assets: Serve /custom_error/...
  if (req.method === 'GET' && req.url.startsWith('/custom_error/')) {
    const cleanUrl = req.url.split('?')[0];
    const relativePath = cleanUrl.replace(/^\/custom_error\//, '');
    const safePath = path.normalize(relativePath).replace(/^(\.\.[\/\\])+/, '');
    const filePath = path.join(BASE_DIR, safePath);

    fs.stat(filePath, (err, stats) => {
      if (err || !stats.isFile()) {
        res.writeHead(404, { 'Content-Type': 'text/plain' });
        return res.end('Not Found');
      }

      const ext = path.extname(filePath).toLowerCase();
      const contentType = MIME_TYPES[ext] || 'application/octet-stream';

      res.writeHead(200, { 'Content-Type': contentType });
      fs.createReadStream(filePath).pipe(res);
    });
    return;
  }

  // Dashboard UI
  if (req.method === 'GET' && (req.url === '/' || req.url === '/index.html')) {
    fs.readFile(path.join(__dirname, 'dashboard.html'), (err, content) => {
      if (err) {
        res.writeHead(500, { 'Content-Type': 'text/plain' });
        return res.end('Error loading dashboard');
      }
      res.writeHead(200, { 'Content-Type': 'text/html' });
      res.end(content);
    });
    return;
  }

  res.writeHead(404, { 'Content-Type': 'text/plain' });
  res.end('Not found');
});

server.listen(PORT, '0.0.0.0', () => {
  console.log(`Error Page Manager running on port ${PORT}`);
});
