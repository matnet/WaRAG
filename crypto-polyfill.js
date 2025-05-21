// Polyfill for crypto module
global.crypto = require('crypto').webcrypto;
