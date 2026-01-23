INSTRUCTIONS:
You will be given the subject and body of an email. You are to determine
whether it appears to be a malicious or a benign message.

EMAIL SUBJECT:
{subject}

EMAIL BODY:
{body}


<!-- For each instance, you should output the results in json format:

{{
    "classification": 1,
    "confidence": 0.95,
    "threat_type": "phishing",
    "risk_indicators": [
        "suspicious_link",
        "requests_money"
    ],
    "reasoning": "The message includes numerous promotional links and fake 'free' offers. It resembles typical phishing//scam content designed to lure the recipient into clicking links or sharing personal details."
}}

Where the classification of 1 means malicious, and the classification of 0 means not malicious. -->
