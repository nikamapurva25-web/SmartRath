/*
whatsapp_bot.js
Node.js WhatsApp gateway using whatsapp-web.js that accepts POST /api/dispatch-alert from FastAPI.

This is a simple, demonstrative script. It requires:
  npm install whatsapp-web.js express body-parser qrcode-terminal

It uses a saved session file 'whatsapp-session.json' to avoid re-auth each run.

Endpoints:
  POST /api/dispatch-alert
    body: { to: "919XXXXXXXXX", message: "...", google_maps_url: "...", image_base64: "..." }
*/

const fs = require('fs');
const express = require('express');
const bodyParser = require('body-parser');
const qrcode = require('qrcode-terminal');
const { Client, LocalAuth, MessageMedia } = require('whatsapp-web.js');

const SESSION_FILE = './whatsapp-session.json';

const app = express();
app.use(bodyParser.json({ limit: '5mb' }));

const client = new Client({
  authStrategy: new LocalAuth({ clientId: "sip-demo" }),
  puppeteer: { headless: true }
});

client.on('qr', (qr) => {
  console.log('[whatsapp] QR received — open WhatsApp on your phone and scan:');
  qrcode.generate(qr, { small: true });
});

client.on('ready', () => {
  console.log('[whatsapp] Client is ready');
});

client.on('auth_failure', (msg) => {
  console.error('[whatsapp] auth failure', msg);
});

client.initialize();

app.post('/api/dispatch-alert', async (req, res) => {
  const { to, message, google_maps_url, image_base64 } = req.body;
  if (!to || !message) {
    return res.status(400).json({ error: 'to and message required' });
  }

  try {
    let media = null;
    if (image_base64) {
      // small images only; message media expects mime + base64
      const data = image_base64.split(',').pop();
      const buffer = Buffer.from(data, 'base64');
      media = new MessageMedia('image/jpeg', buffer.toString('base64'));
    }

    const fullMessage = `${message}\n\n${google_maps_url || ''}`;
    const number = to.includes('@c.us') ? to : `${to}@c.us`;

    if (media) {
      await client.sendMessage(number, media, { caption: fullMessage });
    } else {
      await client.sendMessage(number, fullMessage);
    }

    return res.json({ status: 'sent' });
  } catch (e) {
    console.error('[whatsapp] send error', e);
    return res.status(500).json({ error: String(e) });
  }
});

const PORT = process.env.PORT || 3001;
app.listen(PORT, () => console.log('[whatsapp] listening on port', PORT));
