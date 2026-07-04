import logging
from typing import Optional

logger = logging.getLogger(__name__)

RESPONSES = {
    "greeting": {
        "en": "Hello! How can I help you today?",
        "hi": "नमस्ते! मैं आपकी कैसे सहायता कर सकता हूँ?",
        "bn": "হ্যালো! আমি আপনাকে কীভাবে সাহায্য করতে পারি?",
    },
    "audio_check": {
        "en": "Yes, I can hear you clearly. How can I help you?",
        "hi": "हाँ, मैं आपकी आवाज़ साफ़ सुन पा रहा हूँ। मैं आपकी कैसे सहायता कर सकता हूँ?",
        "bn": "হ্যাঁ, আমি আপনার কথা পরিষ্কার শুনতে পাচ্ছি। আমি আপনাকে কীভাবে সাহায্য করতে পারি?",
    },
    "thanks": {
        "en": "You're welcome! Let me know if you need anything else.",
        "hi": "आपका स्वागत है! अगर आपको और कुछ चाहिए तो बताइएगा।",
        "bn": "আপনাকে স্বাগতম! আর কিছু জানতে চাইলে জানাবেন।",
    },
    "goodbye": {
        "en": "Goodbye! Have a great day. Feel free to call again.",
        "hi": "नमस्ते! आपका दिन शुभ हो। फिर से कॉल करने में संकोच न करें।",
        "bn": "বিদায়! আপনার দিন শুভ হোক। আবার কল করতে দ্বিধা করবেন না।",
    },
    "small_talk": {
        "en": "I'm doing great, thank you! I'm here to help you with college information. How can I assist?",
        "hi": "मैं बढ़िया हूँ, धन्यवाद! मैं यहाँ कॉलेज की जानकारी के लिए हूँ। मैं आपकी कैसे सहायता कर सकता हूँ?",
        "bn": "আমি ভালো আছি, ধন্যবাদ! আমি এখানে কলেজের তথ্যের জন্য আছি। আমি আপনাকে কীভাবে সাহায্য করতে পারি?",
    },
    "confirmation": {
        "en": "Okay, let me know what you need help with.",
        "hi": "ठीक है, बताइए मैं आपकी क्या सहायता कर सकता हूँ।",
        "bn": "ঠিক আছে, জানান আমি আপনাকে কী সাহায্য করতে পারি।",
    },
    "fallback": {
        "en": "I'm sorry, I don't have that specific information. Please call the college at 0343-2501353 for accurate details.",
        "hi": "क्षमा करें, मेरे पास यह विशिष्ट जानकारी नहीं है। कृपया सटीक जानकारी के लिए कॉलेज को 0343-2501353 पर कॉल करें।",
        "bn": "দুঃখিত, আমার কাছে এই নির্দিষ্ট তথ্য নেই। সঠিক তথ্যের জন্য অনুগ্রহ করে কলেজে 0343-2501353 নম্বরে কল করুন।",
    },
}


class ResponseTemplates:
    def get(self, intent: str, language: str = "en", default_lang: str = "en") -> str:
        intent = intent.lower()
        lang = language if language in ("en", "hi", "bn") else default_lang
        intent_map = RESPONSES.get(intent, RESPONSES.get("fallback", {}))
        return intent_map.get(lang, intent_map.get(default_lang, ""))
