#!/usr/bin/env node

const fs = require('fs');
const { spawn } = require('child_process');

// Get API URL from environment variable (set by Fly secrets)
const API_URL = process.env.REACT_APP_API_URL || 'http://localhost:8000';

// Path to the built index.html
const HTML_FILE = '/app/build/index.html';

try {
  if (fs.existsSync(HTML_FILE)) {
    let html = fs.readFileSync(HTML_FILE, 'utf8');
    
    // Create the script tag that sets the global APP_API_URL variable
    const scriptTag = `<script>window.APP_API_URL='${API_URL.replace(/'/g, "\\'")}';</script>`;
    
    // Check if the script tag already exists
    if (html.includes('window.APP_API_URL')) {
      // Replace existing script tag
      html = html.replace(
        /<script>window\.APP_API_URL='[^']*';<\/script>/g,
        scriptTag
      );
    } else {
      // Insert script tag before the closing </head> tag
      html = html.replace('</head>', `${scriptTag}</head>`);
    }
    
    // Write the modified HTML back
    fs.writeFileSync(HTML_FILE, html, 'utf8');
    console.log(`✓ Injected API URL: ${API_URL}`);
  } else {
    console.warn(`Warning: index.html not found at ${HTML_FILE}`);
  }
} catch (error) {
  console.error('Error injecting API URL:', error);
  process.exit(1);
}

// Start the serve command
const serveProcess = spawn('serve', ['-s', 'build', '-l', '8080'], {
  stdio: 'inherit',
  shell: false
});

serveProcess.on('error', (error) => {
  console.error('Error starting serve:', error);
  process.exit(1);
});

serveProcess.on('exit', (code) => {
  process.exit(code);
});
