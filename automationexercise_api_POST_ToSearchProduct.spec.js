import { test, expect } from '@playwright/test';

test('Search Product via API', async ({ request }) => {
  // Send the POST request using the 'form' property
  const startTime = Date.now();
  const response = await request.post('https://automationexercise.com/api/searchProduct', {
    form: {
      search_product: '' // Replace with top, jean, etc.
    }
    
  });

  // Verify the status code is 200
  expect(response.status()).toBe(200);

  // Parse and log the JSON response body with error handling
  let responseBody;
  try {
    responseBody = await response.json();
    console.log('Full API Response:', JSON.stringify(responseBody, null, 2));
  } catch (error) {
    console.error('Failed to parse JSON response:', error);
    console.log('Raw response body:', await response.text());
    // Optionally skip further assertions or mark test as failed
    throw error; // or expect(true).not.toBe(true) to fail the test
  }
  

  // Check price format (should contain 'Rs.')
  const firstProduct = responseBody.products[0];
  expect(firstProduct.price).toContain('Rs.');

  // Check that products have required fields
  const products = responseBody.products; // Fix: use responseBody.products instead of products
  products.forEach(product => {
    expect(product.id).toBeDefined();
    expect(product.name).toBeDefined();
    expect(product.price).toBeDefined();
    expect(product.brand).toBeDefined();
  });


  // Verify the response contains products
  expect(responseBody).toHaveProperty('products');


  // Check for duplicate IDs
  const ids = products.map(p => p.id);
  expect(new Set(ids).size).toBe(ids.length); // All IDs should be unique


  // Verify the products array exists and has at least 1 product
  expect(responseBody.products).toBeDefined();
  expect(responseBody.products.length).toBeGreaterThan(0);


  const duration = Date.now() - startTime;
  console.log(`API Response Time: ${duration}ms`);
  expect(duration).toBeLessThan(5000); // Fails if API takes > 5000ms


  // Make multiple requests and check status
  // for (let i = 0; i < 5; i++) {
  //   await request.post('https://automationexercise.com/api/searchProduct', {
  //     form: { search_product: '' }
  //   });
  // }
  // If no 429 (Too Many Requests) errors, rate limiting is not an issue

  





});
