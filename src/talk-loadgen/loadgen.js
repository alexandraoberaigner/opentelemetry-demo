// Copyright The OpenTelemetry Authors
// SPDX-License-Identifier: Apache-2.0

/**
 * Talk-specific load generator for the OpenFeature + OpenTelemetry demo.
 *
 * Usage:
 *   k6 run -e SCENARIO=background loadgen.js   # warm up all services
 *   k6 run -e SCENARIO=demo1      loadgen.js   # recommendation A/B test burst
 *   k6 run -e SCENARIO=demo2      loadgen.js   # product catalog canary burst
 *
 * All scenarios hit http://localhost:8080 (the Envoy frontend proxy).
 */

import http from 'k6/http';
import { sleep, check } from 'k6';
import crypto from 'k6/crypto';
import { randomItem } from 'https://jslib.k6.io/k6-utils/1.4.0/index.js';

const BASE_URL = __ENV.BASE_URL || 'http://localhost:8080';
const SCENARIO = __ENV.SCENARIO || 'background';

// ── Products & people ────────────────────────────────────────────────────────

const PRODUCTS = [
  '0PUK6V6EV0', '1YMWWN1N4O', '2ZYFJ3GM2N', '66VCHSJNUP',
  '6E92ZMYYFZ', '9SIQT8TOJO', 'L9ECAV7KIM', 'LS4PSXUNUM',
  'OLJCESPC7Z', 'HQTGWGPNH4',
];

const PEOPLE = [
  {
    email: 'someone@example.com',
    address: { streetAddress: '1600 Amphitheatre Pkwy', city: 'Mountain View', state: 'CA', country: 'United States', zipCode: '94043' },
    creditCard: { creditCardNumber: '4432-8015-6152-0454', creditCardCvv: 672, creditCardExpirationMonth: 1, creditCardExpirationYear: 2039 },
  },
  {
    email: 'demo@openfeature.dev',
    address: { streetAddress: 'One Microsoft Way', city: 'Redmond', state: 'WA', country: 'United States', zipCode: '98052' },
    creditCard: { creditCardNumber: '4916-1272-6048-7201', creditCardCvv: 123, creditCardExpirationMonth: 3, creditCardExpirationYear: 2040 },
  },
];

// ── Scenario configurations ───────────────────────────────────────────────────

const SCENARIOS = {
  background: {
    executor: 'constant-vus',
    vus: 3,
    duration: '30m',
  },

  demo1: {
    executor: 'constant-vus',
    vus: 8,
    duration: '30m',
  },

  demo2: {
    executor: 'constant-vus',
    vus: 10,
    duration: '30m',
  },
};

export const options = {
  scenarios: {
    [SCENARIO]: SCENARIOS[SCENARIO],
  },
  tags: { scenario: SCENARIO, synthetic_request: 'true' },
  thresholds: {},
};

// ── Helpers ───────────────────────────────────────────────────────────────────

function randomUserId() {
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, c => {
    const r = Math.random() * 16 | 0;
    return (c === 'x' ? r : (r & 0x3 | 0x8)).toString(16);
  });
}

/** Deterministically derive userTier from a user ID, mirroring
 *  recommendation_server.py:derive_user_tier (SHA-256 last byte % 10 < 7). */
function userTier(userId) {
  const hash = crypto.sha256(userId, 'hex');
  const lastByte = parseInt(hash.slice(-2), 16);
  return (lastByte % 10) < 7 ? 'premium' : 'standard';
}

function headers(userId) {
  return {
    'Content-Type': 'application/json',
    'baggage': `session.id=${userId},synthetic_request=true`,
  };
}

// ── Flows ─────────────────────────────────────────────────────────────────────

/** Demo 1: recommendation impression → conditional checkout */
function demo1Flow() {
  const userId  = randomUserId();
  const product = randomItem(PRODUCTS);
  const h       = headers(userId);

  // 1. Get recommendations (this is the impression the dashboard shows)
  const recResp = http.get(
    `${BASE_URL}/api/recommendations?productIds=${product}&sessionId=${userId}`,
    { headers: h, tags: { flow: 'recommendation' } }
  );
  check(recResp, { 'recommendations 200': r => r.status === 200 });
  sleep(0.2);

  // 2. Determine variant based on SHA-256 userTier — matches the recommendation
  //    service's derive_user_tier() exactly.
  const isPremium      = userTier(userId) === 'premium';
  const conversionRate = isPremium ? 0.85 : 0.45;

  if (Math.random() < conversionRate) {
    // Premium users (personalized) buy 2-3 items → higher AOV.
    // Standard users (popularity) buy 1 item → lower AOV.
    // Both pick from the full product list — the difference comes from basket size.
    const itemCount = isPremium ? Math.floor(Math.random() * 2) + 2 : 1;
    const usedProducts = new Set();

    for (let i = 0; i < itemCount; i++) {
      let cartProduct = randomItem(PRODUCTS);
      while (usedProducts.has(cartProduct) && usedProducts.size < PRODUCTS.length) {
        cartProduct = randomItem(PRODUCTS);
      }
      usedProducts.add(cartProduct);

      http.post(`${BASE_URL}/api/cart`, JSON.stringify({
        item: { productId: cartProduct, quantity: 1 },
        userId,
      }), { headers: h, tags: { flow: 'add_to_cart' } });
      sleep(0.05);
    }
    sleep(0.1);

    // Checkout
    const person = randomItem(PEOPLE);
    const checkoutResp = http.post(
      `${BASE_URL}/api/checkout?currencyCode=USD`,
      JSON.stringify({ ...person, userId, userCurrency: 'USD' }),
      { headers: h, tags: { flow: 'checkout' } }
    );
    check(checkoutResp, { 'checkout 200': r => r.status === 200 });
  }

  sleep(Math.random() * 2 + 0.5);
}

/** Demo 2: product catalog browsing — triggers canary flag evaluation */
function demo2Flow() {
  const userId  = randomUserId();
  const product = randomItem(PRODUCTS);
  const h       = headers(userId);

  const resp = http.get(
    `${BASE_URL}/api/products/${product}?sessionId=${userId}`,
    { headers: h, tags: { flow: 'get_product' } }
  );
  check(resp, {
    'product found': r => r.status === 200,
    'not v2 error':  r => r.status !== 500,
  });
  sleep(0.1);

  if (Math.random() < 0.3) {
    http.get(`${BASE_URL}/api/products`, { headers: h, tags: { flow: 'list_products' } });
    sleep(0.1);
  }

  sleep(Math.random() * 1 + 0.2);
}

/** Background: light traffic across all services to keep everything warm. */
function backgroundFlow() {
  const userId  = randomUserId();
  const product = randomItem(PRODUCTS);
  const h       = headers(userId);

  const actions = [
    () => http.get(`${BASE_URL}/`,                                                { headers: h }),
    () => http.get(`${BASE_URL}/api/products/${product}`,                         { headers: h }),
    () => http.get(`${BASE_URL}/api/recommendations?productIds=${product}&sessionId=${userId}`, { headers: h }),
    () => http.get(`${BASE_URL}/api/data/?contextKeys=telescopes`,                { headers: h }),
    () => http.get(`${BASE_URL}/api/cart`,                                        { headers: h }),
  ];

  randomItem(actions)();
  sleep(Math.random() * 3 + 1);
}

// ── Entry point ───────────────────────────────────────────────────────────────

export default function () {
  switch (SCENARIO) {
    case 'demo1':      demo1Flow();      break;
    case 'demo2':      demo2Flow();      break;
    case 'background': backgroundFlow(); break;
    default:
      console.error(`Unknown scenario: ${SCENARIO}. Use background, demo1, or demo2.`);
  }
}
