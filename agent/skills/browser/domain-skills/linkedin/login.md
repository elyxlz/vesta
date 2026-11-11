# LinkedIn: signing in with email and password

The login page (`https://www.linkedin.com/login`) renders TWO copies of the form. Only the visible
copy submits, and the input ids are generated per load (`_R_...`), so `#username` / `#password`
selectors do not exist.

`fill_input` and click-then-`type_text` both leave the visible inputs empty here: the React form
re-renders after hydration and drops a value set too early. What works is waiting for the network
to settle, then setting the value through the native setter and firing `input` and `change`:

```python
goto_url("https://www.linkedin.com/login")
wait_for_load()
wait_for_network_idle(timeout=10)
wait(4)
lengths = js("""(() => {
  const v = [...document.querySelectorAll('input[type=email],input[type=password]')].filter(i => i.offsetParent);
  const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
  const vals = [EMAIL, PASSWORD];  // substitute; never print them
  v.forEach((i, k) => { i.focus(); set.call(i, vals[k]); i.dispatchEvent(new Event('input', {bubbles: true})); i.dispatchEvent(new Event('change', {bubbles: true})); });
  return v.map(i => i.value.length).join(',');
})()""")
js("""[...document.querySelectorAll('button')].find(b => /^\\s*Sign in\\s*$/.test(b.innerText) && b.offsetParent).click()""")
wait(10)
signed_in = "/feed" in js("location.href")
```

Check the printed lengths are non-zero before submitting: a `0` means the values were dropped again.
A sign-in from a new IP can land on an email-code checkpoint instead of `/feed`; the code goes to the
account's email.

Before editing a profile on someone's behalf, have them turn off Settings, Visibility, "Share profile
updates with your network", or every saved edit is announced to their connections.
