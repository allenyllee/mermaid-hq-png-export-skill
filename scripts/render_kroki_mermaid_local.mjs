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
  const outputSvg = path.resolve(args.outputSvg || '');
  const moduleRoot = path.resolve(args.moduleRoot || '');
  const chromePath = path.resolve(args.chromePath || '');

  if (!inputPath) {
    throw new Error('--input is required');
  }
  if (!outputSvg) {
    throw new Error('--outputSvg is required');
  }
  if (!moduleRoot) {
    throw new Error('--moduleRoot is required');
  }
  if (!chromePath) {
    throw new Error('--chromePath is required');
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
      deviceScaleFactor: 1,
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
        mermaid.initialize({ startOnLoad: false });
        const rendered = await mermaid.render('container', diagramSource);
        return { svg: rendered.svg };
      } catch (error) {
        return { error: String(error && error.stack ? error.stack : error) };
      }
    }, source);

    if (result.error) {
      throw new Error(`Kroki-local Mermaid render failed: ${result.error}`);
    }

    fs.mkdirSync(path.dirname(outputSvg), { recursive: true });
    fs.writeFileSync(outputSvg, result.svg, 'utf8');
    process.stdout.write(`${JSON.stringify({ svg: outputSvg })}\n`);
  } finally {
    await browser.close();
  }
}

main().catch((error) => {
  process.stderr.write(`${error && error.stack ? error.stack : String(error)}\n`);
  process.exit(1);
});
