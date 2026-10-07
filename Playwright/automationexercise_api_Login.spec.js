import { test, expect } from '@playwright/test';


test('API POST To Create User Account', async ({ request }) => {
  // generation of uniq email
  const uniqueemail = `test_${Date.now()}@gmail.com`;
  
  // Send the POST request with all required form parameters
  const response = await request.post('https://automationexercise.com/api/createAccount', {
    form: {
      name: 'John Doe',
      email: uniqueemail, // Unique email per run
      password: 'SecurePassword123',
      title: 'Mr',
      birth_date: '15',
      birth_month: '05',
      birth_year: '1990',
      firstname: 'John',
      lastname: 'Doe',
      company: 'Tech Corp',
      address1: '123 Main Street',
      address2: 'Suite 400',
      country: 'United States',
      zipcode: '90210',
      state: 'California',
      city: 'Los Angeles',
      mobile_number: '1234567890'
    }
  });


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

  expect(responseBody.responseCode).toBe(201);
  expect(responseBody.message).toBe('User created!');


});
