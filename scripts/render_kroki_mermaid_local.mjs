#!/usr/bin/env node

import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';

function parseArgs(argv) {
  const args = {};
  for (let i = 0; i < argv.length; i += 1) {
    const key = argv[i];
    if (!key.startsWith('--')) {
      throw new Error(`Unexpected argument: ${key}`);
    }
    const value = argv[i + 1];
    if (!value || value.startsWith('--')) {
      throw new Error(`Missing value for ${key}`);
    }
    args[key.slice(2)] = value;
    i += 1;
  }
  return args;
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const inputPath = path.resolve(args.input || '');
  const outputSvg = args.outputSvg ? path.resolve(args.outputSvg) : '';
  const outputPng = args.outputPng ? path.resolve(args.outputPng) : '';
  const moduleRoot = path.resolve(args.moduleRoot || '');
  const chromePath = path.resolve(args.chromePath || '');
  const scale = Number(args.scale || '1');

  if (!inputPath) {
    throw new Error('--input is required');
  }
  if (!outputSvg && !outputPng) {
    throw new Error('At least one of --outputSvg or --outputPng is required');
  }
  if (!moduleRoot) {
    throw new Error('--moduleRoot is required');
  }
  if (!chromePath) {
    throw new Error('--chromePath is required');
  }
  if (!Number.isFinite(scale) || scale <= 0) {
    throw new Error('--scale must be > 0');
  }

  const requireFromRoot = createRequire(path.join(moduleRoot, 'resolver.cjs'));
  const puppeteer = requireFromRoot('puppeteer-core');
  const mermaidBundlePath = requireFromRoot.resolve('mermaid/dist/mermaid.min.js');
  const mermaidBundle = fs.readFileSync(mermaidBundlePath, 'utf8').replace(/<\/script/gi, '<\\/script');
  const source = fs.readFileSync(inputPath, 'utf8');

  const browser = await puppeteer.launch({
    executablePath: chromePath,
    headless: true,
    args: [
      '--no-sandbox',
      '--disable-setuid-sandbox',
      '--disable-dev-shm-usage',
    ],
    defaultViewport: {
      width: 800,
      height: 600,
      deviceScaleFactor: scale,
    },
  });

  try {
    const page = await browser.newPage();
    const html = `<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <style>
    html, body {
      margin: 0;
      padding: 0;
      background: transparent;
    }
    #container {
      display: block;
    }
  </style>
</head>
<body>
  <div id="container"></div>
  <script>${mermaidBundle}</script>
</body>
</html>`;
    await page.setContent(html, { waitUntil: 'load' });
    const result = await page.evaluate(async (diagramSource) => {
      try {
        await Promise.all(Array.from(document.fonts, (font) => font.load()));
        const container = document.getElementById('container');
        if (!container) {
          throw new Error('Render container not found');
        }
        mermaid.initialize({ startOnLoad: false });
        const rendered = await mermaid.render('kroki-local-svg', diagramSource);
        container.innerHTML = rendered.svg;
        const svg = container.getElementsByTagName('svg')[0];
        if (!svg) {
          throw new Error('Rendered output does not contain an svg element');
        }
        const xmlSerializer = new XMLSerializer();
        return { svg: xmlSerializer.serializeToString(svg) };
      } catch (error) {
        return { error: String(error && error.stack ? error.stack : error) };
      }
    }, source);

    if (result.error) {
      throw new Error(`Kroki-local Mermaid render failed: ${result.error}`);
    }

    const clip = await page.$eval('svg', (svg) => {
      const rect = svg.getBoundingClientRect();
      return {
        x: Math.floor(rect.left),
        y: Math.floor(rect.top),
        width: Math.ceil(rect.width),
        height: Math.ceil(rect.height),
      };
    });

    if (outputSvg) {
      fs.mkdirSync(path.dirname(outputSvg), { recursive: true });
      fs.writeFileSync(outputSvg, result.svg, 'utf8');
    }
    if (outputPng) {
      fs.mkdirSync(path.dirname(outputPng), { recursive: true });
      await page.setViewport({ width: clip.x + clip.width, height: clip.y + clip.height, deviceScaleFactor: scale });
      await page.screenshot({ path: outputPng, clip, omitBackground: true });
    }
    process.stdout.write(`${JSON.stringify({ svg: outputSvg, png: outputPng, width: clip.width, height: clip.height })}\n`);
  } finally {
    await browser.close();
  }
}

main().catch((error) => {
  process.stderr.write(`${error && error.stack ? error.stack : String(error)}\n`);
  process.exit(1);
});
