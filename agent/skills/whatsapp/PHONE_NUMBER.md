# Getting a Separate Phone Number for WhatsApp

Vesta needs its own WhatsApp account with a dedicated phone number. **Do not use your personal WhatsApp** - Vesta will read and send messages from whatever account it's linked to.

You need a real mobile number from an actual carrier. Most VoIP/virtual numbers (Google Voice, TextNow, Skype) are blocked by WhatsApp.

## Step 1: Get a Number

### Cheapest Options by Region

**UK**
| Provider | Type | Cost | Keep-alive |
|---|---|---|---|
| giffgaff | SIM / eSIM | Free SIM, £5 PAYG top-up | Top up every 6 months |
| Lyca Mobile | SIM / eSIM | From £5/month PAYG | Use within 90 days |
| Smarty (Three) | SIM / eSIM | From £4/month, no contract | Cancel anytime |
| Asda Mobile | SIM | Free SIM, £5 top-up | Top up every 3 months |

**US**
| Provider | Type | Cost | Keep-alive |
|---|---|---|---|
| Tello | SIM / eSIM | From $5/month | Any activity every 90 days |
| US Mobile | SIM / eSIM | From $4/month (light plan) | Active plan required |
| Hello Mobile | SIM / eSIM | $5/month | Active plan required |
| Mint Mobile | SIM / eSIM | From $15/month | Active plan required |
| T-Mobile Connect | SIM / eSIM | From $10/month | Active plan required |

**EU**
| Provider | Type | Cost | Keep-alive |
|---|---|---|---|
| Free Mobile (France) | SIM / eSIM | 2 EUR/month | Active plan required |
| Simyo (Germany) | SIM | From 3.99 EUR/month | Active plan required |
| Iliad (Italy) | SIM / eSIM | From 4.99 EUR/month | Active plan required |
| Lebara | SIM / eSIM | From 5 EUR/month PAYG | Varies by country |
| Lycamobile | SIM / eSIM | From 5 EUR/month PAYG | Use within 90 days |

**Other Regions** - look for the cheapest prepaid PAYG SIM from a local carrier. Avoid data-only eSIMs (Airalo, Holafly, etc.) as they don't provide a phone number and can't receive the WhatsApp verification SMS.

### eSIM vs Physical SIM

**eSIM** (recommended): Instant activation via QR code, no waiting for delivery. Works on most phones from 2018+. Ideal if you're setting up WhatsApp on your primary phone via a second account or work profile.

**Physical SIM**: Works on any unlocked phone. Better if you're using a cheap dedicated phone for the agent. May require visiting a store or waiting for delivery.

## Step 2: Register WhatsApp with the New Number

You need WhatsApp installed somewhere to register the number. There are several approaches depending on your device.

### Option A: Use WhatsApp's Built-in Multi-Account (Recommended)

WhatsApp now natively supports two accounts on a single device (Android and iPhone). This is the simplest method.

**Android (WhatsApp 2.24.3+):**
1. Open WhatsApp > Settings > tap the arrow next to your name > **Add Account**
2. Enter your new number and verify via SMS
3. Each account has separate chats, notifications, and settings

**iPhone (WhatsApp 25.11.3+):**
1. Open WhatsApp > Settings > tap the arrow next to your name > **Add Account**
2. Enter your new number and verify via SMS
3. Tap your profile icon to switch between accounts

### Option B: Work Profile (Android)

Creates a fully isolated second copy of WhatsApp. Good if you want complete separation.

1. Install **Shelter** (F-Droid, open source) or **Island** (Play Store)
2. These apps create an Android Work Profile - a sandboxed environment
3. Clone WhatsApp into the work profile
4. Open the cloned WhatsApp and register with your new number

**Samsung** has this built in: Settings > Advanced Features > Dual Messenger > toggle WhatsApp > Install.

**Xiaomi/MIUI**: Settings > Apps > Dual Apps > toggle WhatsApp.

### Option C: WhatsApp Business App

Install both "WhatsApp" (personal) and "WhatsApp Business" (for the agent) from your app store. They're separate apps that can each be registered to a different number. Works on both Android and iPhone.

### Option D: Cheap Spare Phone

Buy any cheap Android phone (even used, even without its own SIM after initial setup). Register WhatsApp on it with the new number. WhatsApp's multi-device feature means the agent can operate independently once linked - the spare phone doesn't need to stay online permanently, but WhatsApp may require periodic re-verification.

## Step 3: Link to Vesta

Once WhatsApp is registered with the new number, follow the main SETUP.md to authenticate Vesta by scanning the QR code from the new account. The QR code links Vesta as a companion device.

## Important Warnings

**Keep the number active.** Prepaid numbers expire if unused. Set a reminder to top up or make a call before expiry (typically every 60-180 days depending on carrier). If the number expires and gets recycled, you lose the WhatsApp account permanently.

**WhatsApp may re-verify.** Occasionally WhatsApp asks you to re-verify via SMS. You must be able to receive a text at the registered number when this happens. Don't discard the SIM after setup.

**Unofficial API risk.** Vesta uses an unofficial WhatsApp bridge (whatsmeow), not the official WhatsApp Business API. This technically violates WhatsApp's ToS. Bans are rare with normal usage patterns but possible. Avoid mass messaging or spammy behavior. Let the number "age" with a few days of normal manual use before connecting to Vesta.

**Number recycling.** If your prepaid number expires, the carrier will eventually reassign it. The new owner could register WhatsApp with that number, permanently disconnecting your agent.
