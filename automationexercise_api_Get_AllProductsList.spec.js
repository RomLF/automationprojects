import {test,expect} from "@playwright/test"


test ("Get All Products List",async function({request}){
    
    // Traces this entire network transaction
    const resp= await request.get("https://automationexercise.com/api/productsList")

    // Active Assertions CODES
    const ressstatus=resp.statusText// Retrieves status text
    await expect(resp.status()).toBe(200)// Asserts status is 200
    await expect(resp).toBeOK("OK")// Verifies response is OK
    expect(resp.ok()).toBeTruthy// Assert the response is a success status (2xx/3xx) using the 'ok' property check.
    console.log(ressstatus)// Logs status text
    
    // Log headers as key-value pairs for readability
    const responseheaders = resp.headers()
    console.log('--- Headers ---')
    console.log(responseheaders)

    //* Retrieves raw response body and logs it; note: returns a Buffer */
    const responseBody = await resp.body();
    console.log(responseBody);

     // Log JSON response (Playwright usually handles the object printing well)
    const responsejson = await resp.json();
    console.log('--- Response JSON ---')
    console.log(responsejson);

    // Scans the array for a partial object match, verifying that AT LEAST ONE product contains both 'id: 42' AND the specified name.
    expect(responsejson.products).toContainEqual(expect.objectContaining({ id: 42, name: 'Lace Top For Women' }));

    // Asserts that the products array successfully contains an item combining an 'id' of 5 with a 'Mast & Harbour' brand name.
    expect(responsejson.products.some(p => p.id === 5 && p.brand === 'Mast & Harbour')).toBe(true);
    
    // Asserts that the products array does not contain any item combining an 'id' of 5 with a 'Polo' brand name.
    expect(responsejson.products.some(p => p.id === 5 && p.brand === 'Polo')).toBe(false);


    
})