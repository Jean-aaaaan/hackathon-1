const http = require('http');
const fs = require('fs');
const path = require('path');
const { WebSocketServer } = require('ws');
const { exec } = require('child_process');

const PORT = 3333;
const FEED_PATH = path.resolve(__dirname, '..', 'live-feed.jsonl');
const PUBLIC_DIR = path.join(__dirname, 'public');
const MAX_REPLAY_EVENTS = 50;

// MIME types for static file serving
const MIME = {
  '.html': 'text/html',
  '.css': 'text/css',
  '.js': 'application/javascript',
  '.json': 'application/json',
  '.png': 'image/png',
  '.svg': 'image/svg+xml',
};

// --- Feed file management ---

// Create feed file if it doesn't exist (this is the opt-in signal for SKILL.md)
if (!fs.existsSync(FEED_PATH)) {
  fs.writeFileSync(FEED_PATH, '', 'utf8');
  console.log(`Created ${FEED_PATH} (agents will now emit events)`);
}

let feedOffset = 0;
let recentEvents = [];

// Load existing events from feed file
function loadExistingEvents() {
  try {
    const content = fs.readFileSync(FEED_PATH, 'utf8');
    feedOffset = Buffer.byteLength(content, 'utf8');
    const lines = content.split('\n').filter(l => l.trim());
    for (const line of lines) {
      try {
        recentEvents.push(JSON.parse(line));
      } catch (e) {
        // Skip malformed lines
      }
    }
    // Keep only last N events
    if (recentEvents.length > MAX_REPLAY_EVENTS) {
      recentEvents = recentEvents.slice(-MAX_REPLAY_EVENTS);
    }
    console.log(`Loaded ${recentEvents.length} existing events (offset: ${feedOffset})`);
  } catch (e) {
    console.log('Starting with empty feed');
  }
}

// Read new events from feed file
function readNewEvents() {
  try {
    const stat = fs.statSync(FEED_PATH);

    // File was truncated — reset
    if (stat.size < feedOffset) {
      feedOffset = 0;
      recentEvents = [];
    }

    if (stat.size === feedOffset) return [];

    // Read only new bytes
    const fd = fs.openSync(FEED_PATH, 'r');
    const buf = Buffer.alloc(stat.size - feedOffset);
    fs.readSync(fd, buf, 0, buf.length, feedOffset);
    fs.closeSync(fd);
    feedOffset = stat.size;

    const newContent = buf.toString('utf8');
    const lines = newContent.split('\n').filter(l => l.trim());
    const newEvents = [];

    for (const line of lines) {
      try {
        const event = JSON.parse(line);
        newEvents.push(event);
        recentEvents.push(event);
      } catch (e) {
        console.warn('Skipping malformed line:', line.substring(0, 80));
      }
    }

    // Trim recent events buffer
    if (recentEvents.length > MAX_REPLAY_EVENTS) {
      recentEvents = recentEvents.slice(-MAX_REPLAY_EVENTS);
    }

    return newEvents;
  } catch (e) {
    return [];
  }
}

// --- HTTP Server ---

const server = http.createServer((req, res) => {
  let filePath = req.url === '/' ? '/index.html' : req.url;
  filePath = path.join(PUBLIC_DIR, filePath);

  // Security: prevent directory traversal
  if (!filePath.startsWith(PUBLIC_DIR)) {
    res.writeHead(403);
    res.end('Forbidden');
    return;
  }

  const ext = path.extname(filePath);
  const contentType = MIME[ext] || 'application/octet-stream';

  fs.readFile(filePath, (err, data) => {
    if (err) {
      if (err.code === 'ENOENT') {
        res.writeHead(404);
        res.end('Not Found');
      } else {
        res.writeHead(500);
        res.end('Internal Server Error');
      }
      return;
    }
    res.writeHead(200, { 'Content-Type': contentType });
    res.end(data);
  });
});

// --- WebSocket Server ---

const wss = new WebSocketServer({ server });

wss.on('connection', (ws) => {
  console.log('Browser connected');

  // Send recent events for state reconstruction
  ws.send(JSON.stringify({ type: 'init', events: recentEvents }));

  ws.on('message', (data) => {
    try {
      const msg = JSON.parse(data);
      // Handle replay request from reconnecting client
      if (msg.type === 'replay' && msg.last_ts) {
        const idx = recentEvents.findIndex(e => e.ts === msg.last_ts);
        const missed = idx >= 0 ? recentEvents.slice(idx + 1) : recentEvents;
        ws.send(JSON.stringify({ type: 'init', events: missed }));
      }
    } catch (e) {
      // Ignore invalid messages
    }
  });

  ws.on('close', () => {
    console.log('Browser disconnected');
  });
});

function broadcast(events) {
  const msg = JSON.stringify({ type: 'events', events });
  for (const client of wss.clients) {
    if (client.readyState === 1) { // OPEN
      client.send(msg);
    }
  }
}

// --- File Watcher ---

let debounceTimer = null;

function onFeedChange() {
  if (debounceTimer) clearTimeout(debounceTimer);
  debounceTimer = setTimeout(() => {
    const newEvents = readNewEvents();
    if (newEvents.length > 0) {
      console.log(`Broadcasting ${newEvents.length} new event(s)`);
      broadcast(newEvents);
    }
  }, 100); // 100ms debounce
}

// Primary: fs.watch
try {
  fs.watch(FEED_PATH, (eventType) => {
    if (eventType === 'change') onFeedChange();
  });
  console.log('File watcher active');
} catch (e) {
  console.warn('fs.watch failed, relying on polling only');
}

// Fallback: poll every 2s (Windows fs.watch can miss events)
setInterval(() => {
  try {
    const stat = fs.statSync(FEED_PATH);
    if (stat.size !== feedOffset) {
      onFeedChange();
    }
  } catch (e) {
    // File might be temporarily unavailable
  }
}, 2000);

// --- Start ---

loadExistingEvents();

server.listen(PORT, () => {
  const url = `http://localhost:${PORT}`;
  console.log(`\n  BMAD Live Visualization`);
  console.log(`  ${url}\n`);
  console.log(`  Watching: ${FEED_PATH}`);
  console.log(`  Press Ctrl+C to stop\n`);

  // Auto-open browser
  const cmd = process.platform === 'win32' ? `start ${url}`
    : process.platform === 'darwin' ? `open ${url}`
    : `xdg-open ${url}`;
  exec(cmd, (err) => {
    if (err) console.log('Could not auto-open browser. Open manually:', url);
  });
});
