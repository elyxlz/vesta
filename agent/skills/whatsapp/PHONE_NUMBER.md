# Getting a Separate Phone Number for WhatsApp

Vesta needs its own WhatsApp account with a dedicated phone number. **Do not use your personal WhatsApp.** Vesta will read and send messages from whatever account it's linked to.

You need a real mobile number from an actual carrier. Most VoIP/virtual numbers (Google Voice, TextNow, Skype) are blocked by WhatsApp.

## Contents

- [Vesta Switchboard](#vesta-cloud-acquire-one-from-switchboard)
- [Bring your own carrier number](#bring-your-own-carrier-number)
- [Get a number](#step-1-get-a-number)
- [Register WhatsApp](#step-2-register-whatsapp-with-the-new-number)
- [Link to Vesta](#step-3-link-to-vesta)
- [Warnings](#important-warnings)

## Vesta Cloud: acquire one from Switchboard

For a self-managed account on Vesta Cloud, `whatsapp connect --own-number` asks
Vesta Switchboard for a number lease and relays its verification SMS. The user
still registers WhatsApp on their own phone; Double Tick is not involved. Follow
[SETUP_SELF_MANAGED.md](SETUP_SELF_MANAGED.md) for the complete flow.

Switchboard retains the carrier-number/SIM lease and handles later SMS recovery.
Do not promise that the user can port, independently re-verify, or retain that
number outside the Switchboard agreement.

## Bring your own carrier number

## Step 1: Get a Number

### Cheapest Options by Region

**UK**
| Provider | Type | Cost | Keep-alive |
|---|---|---|---|
| Lyca Mobile | SIM / eSIM | From £5/month PAYG | Use within 90 days |
| giffgaff | SIM / eSIM | Free SIM, £5 PAYG top-up | Top up every 6 months |
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

**Other Regions**: look for the cheapest prepaid PAYG SIM from a local carrier. Avoid data-only eSIMs (Airalo, Holafly, etc.) as they don't provide a phone number and can't receive the WhatsApp verification SMS.

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
1. WhatsApp gates this feature by rollout and it's currently never visible in Settings by default, so first open this deeplink on the iPhone to activate it: `https://wa.me/settings?showAddAccountTooltip=true`. It opens WhatsApp Settings with the **Add Account** option surfaced.
2. Tap the arrow next to your name > **Add Account**
3. Enter your new number and verify via SMS
4. Tap your profile icon to switch between accounts

If the deeplink doesn't surface **Add Account** and you still can't find the multi-account option, use the WhatsApp Business app instead (Option C below): it's a separate app you can register to the new number without touching your personal WhatsApp.

### Option B: Work Profile (Android)

Creates a fully isolated second copy of WhatsApp. Good if you want complete separation.

1. Install **Shelter** (F-Droid, open source) or **Island** (Play Store)
2. These apps create an Android Work Profile (a sandboxed environment)
3. Clone WhatsApp into the work profile
4. Open the cloned WhatsApp and register with your new number

**Samsung** has this built in: Settings > Advanced Features > Dual Messenger > toggle WhatsApp > Install.

**Xiaomi/MIUI**: Settings > Apps > Dual Apps > toggle WhatsApp.

### Option C: WhatsApp Business App

Install both "WhatsApp" (personal) and "WhatsApp Business" (for the agent) from your app store. They're separate apps that can each be registered to a different number. Works on both Android and iPhone.

### Option D: Cheap Spare Phone

Buy any cheap Android phone (even used, even without its own SIM after initial setup). Register WhatsApp on it with the new number. WhatsApp's multi-device feature means the agent can operate independently once linked. The spare phone doesn't need to stay online permanently, but WhatsApp may require periodic re-verification.

## Step 3: Link to Vesta

Once WhatsApp is registered with the new number, follow
[SETUP_SELF_MANAGED.md](SETUP_SELF_MANAGED.md) to link Vesta as a companion.

## Important Warnings

**Keep a user-provided number active.** Prepaid numbers expire if unused. Set a reminder to top up or make a call before expiry (typically every 60-180 days depending on carrier). If the number expires and gets recycled, you lose the WhatsApp account permanently. A Switchboard number is a single-use verification lease, not a number you keep alive, so these top-up and expiry warnings do not apply to it.

**WhatsApp may re-verify.** Occasionally WhatsApp asks you to re-verify via SMS. For a user-provided number, keep access to its SIM. For a Switchboard number, request the SMS through Switchboard.

**Make the first message an incoming one.** Before Vesta sends anything from the new account, message the new number from your own personal phone first, so its first interaction is receiving a message rather than sending one.

**Number recycling.** If your prepaid number expires, the carrier will eventually reassign it. The new owner could register WhatsApp with that number, permanently disconnecting your agent.
