const { test, expect } = require('@playwright/test');

// 'test.describe' groups your automation steps
test.describe('Jones Automation Exercise', () => {

  test('should fill out the form and submit', async ({ page }) => {
    await page.goto('https://test.netlify.app/');
    
    // Step 1: Type values in Name, Email, Phone, etc.
    await page.fill('input[name="name"]', 'John Doe');
    await page.fill('input[name="email"]', 'john.doe@example.com');
    await page.fill('input[name="phone"]', '123-456-7890');
    await page.fill('input[name="company"]', 'Jones Automation Inc.');
    await page.fill('input[name="website"]', 'https://www.jones-automation.com');


    // 2. Change the Number of Employees to 51-500
    await page.getByLabel('Number of Employees').selectOption('51-500');

    
    // Step 3: Take screenshot AND save it for comparison
    let myPicture = await page.screenshot({ path: 'before-callback.png', fullPage: true });


    // Step 4: Click "Request a call back"
    await page.getByRole('button', { name: 'Request a call back' }).click();


    // Step 5: console.log on thank you page
    await page.waitForSelector('h1:has-text("Thank You!")');
    console.log("Successfully reached the thank you page.");

  });

});