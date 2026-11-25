// QR code for the flyer, made on your own computer: npm run qr -- https://advent-prijave.<račun>.workers.dev/
// Writes qr/qr-prijave.svg (vector, best for print) and qr/qr-prijave.png (about 1500 × 1500 px, 300 dpi).
import { mkdirSync, writeFileSync } from 'node:fs';
import { qrSvg, qrPng } from '../src/qr.js';

const url = process.argv[2];
if (!url || !/^https:\/\//.test(url)) {
  console.error('Upotreba: npm run qr -- https://adresa-stranice/');
  process.exit(1);
}
mkdirSync('qr', { recursive: true });
writeFileSync('qr/qr-prijave.svg', qrSvg(url));
writeFileSync('qr/qr-prijave.png', await qrPng(url, 40));
writeFileSync('qr/qr-prijave-veliki.png', await qrPng(url, 80));
console.log(`QR kod za ${url} je u mapi qr/: qr-prijave.svg, qr-prijave.png, qr-prijave-veliki.png`);
