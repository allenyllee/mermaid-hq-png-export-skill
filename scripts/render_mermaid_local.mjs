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
  const outputPng = args.output ? path.resolve(args.output) : '';
  const outputSvg = args.outputSvg ? path.resolve(args.outputSvg) : '';
  const moduleRoot = path.resolve(args.moduleRoot || '');
  const chromePath = path.resolve(args.chromePath || '');
  const scale = Number(args.scale || '4');

  if (!inputPath) {
    throw new Error('--input is required');
  }
  if (!outputPng && !outputSvg) {
    throw new Error('At least one of --output or --outputSvg is required');
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
      '--allow-file-access-from-files',
    ],
    defaultViewport: {
      width: 4096,
      height: 4096,
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
      width: max-content;
      height: max-content;
    }
    #container {
      display: inline-block;
      background: transparent;
    }
    svg {
      display: block;
      max-width: none !important;
    }
  </style>
</head>
<body>
  <div id="container"></div>
  <script>${mermaidBundle}</script>
  <script type="module">
    const source = ${JSON.stringify(source)};
    const container = document.getElementById('container');
    window.addEventListener('error', (event) => {
      window.__renderError = String(event.error && event.error.stack ? event.error.stack : event.message);
    });
    window.addEventListener('unhandledrejection', (event) => {
      const reason = event.reason;
      window.__renderError = String(reason && reason.stack ? reason.stack : reason);
    });
    (async () => {
      try {
        const mermaid = window.mermaid;
        mermaid.initialize({
          startOnLoad: false,
          securityLevel: 'loose',
          flowchart: { htmlLabels: false },
        });
        const renderResult = await mermaid.render('mermaid-local-render', source);
        container.innerHTML = renderResult.svg;
        const svg = container.querySelector('svg');
        if (svg) {
          svg.style.maxWidth = 'none';
        }
        window.__renderResult = {
          svg: container.innerHTML,
          width: Math.ceil(svg?.getBoundingClientRect().width || 0),
          height: Math.ceil(svg?.getBoundingClientRect().height || 0),
        };
      } catch (error) {
        window.__renderError = String(error && error.stack ? error.stack : error);
      }
    })();
  </script>
</body>
</html>`;

    await page.setContent(html, { waitUntil: 'load' });
    await page.waitForFunction(() => Boolean(window.__renderResult || window.__renderError), {
      timeout: 30000,
    });

    const renderError = await page.evaluate(() => window.__renderError || '');
    if (renderError) {
      throw new Error(`Mermaid render failed: ${renderError}`);
    }

    const renderResult = await page.evaluate(() => window.__renderResult);
    if (!renderResult || !renderResult.svg) {
      throw new Error('Mermaid render did not produce SVG output');
    }

    if (outputSvg) {
      fs.mkdirSync(path.dirname(outputSvg), { recursive: true });
      fs.writeFileSync(outputSvg, renderResult.svg, 'utf8');
    }

    if (outputPng) {
      const element = await page.$('#container svg');
      if (!element) {
        throw new Error('Rendered page does not contain an <svg> element');
      }
      fs.mkdirSync(path.dirname(outputPng), { recursive: true });
      await element.screenshot({
        path: outputPng,
        omitBackground: true,
      });
    }

    const payload = {
      width: renderResult.width,
      height: renderResult.height,
      png: outputPng,
      svg: outputSvg,
    };
    process.stdout.write(`${JSON.stringify(payload)}\n`);
  } finally {
    await browser.close();
  }
}

main().catch((error) => {
  process.stderr.write(`${error && error.stack ? error.stack : String(error)}\n`);
  process.exit(1);
});
