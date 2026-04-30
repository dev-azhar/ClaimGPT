"use client";

/**
 * Lightweight i18n: 14 languages (English + Hindi + 12 Indian regional).
 * - Persists choice to localStorage
 * - Updates <html lang> + dir on change
 * - Falls back to English for missing keys
 *
 * Translations are intentionally partial for non-English/Hindi locales; the
 * switcher proves the surface works end-to-end and additional strings can be
 * filled in incrementally without touching call sites.
 */

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

export type LangCode =
  | "en" | "hi" | "bn" | "te" | "mr" | "ta" | "ur"
  | "gu" | "kn" | "or" | "pa" | "ml" | "as" | "sa";

export interface LanguageMeta {
  code: LangCode;
  english: string;
  native: string;
  rtl?: boolean;
}

/* Order shown in the picker. English & Hindi pinned to top. */
export const LANGUAGES: LanguageMeta[] = [
  { code: "en", english: "English",   native: "English"     },
  { code: "hi", english: "Hindi",     native: "हिन्दी"      },
  { code: "bn", english: "Bengali",   native: "বাংলা"        },
  { code: "te", english: "Telugu",    native: "తెలుగు"       },
  { code: "mr", english: "Marathi",   native: "मराठी"        },
  { code: "ta", english: "Tamil",     native: "தமிழ்"        },
  { code: "ur", english: "Urdu",      native: "اردو", rtl: true },
  { code: "gu", english: "Gujarati",  native: "ગુજરાતી"      },
  { code: "kn", english: "Kannada",   native: "ಕನ್ನಡ"        },
  { code: "or", english: "Odia",      native: "ଓଡ଼ିଆ"         },
  { code: "pa", english: "Punjabi",   native: "ਪੰਜਾਬੀ"        },
  { code: "ml", english: "Malayalam", native: "മലയാളം"      },
  { code: "as", english: "Assamese",  native: "অসমীয়া"       },
  { code: "sa", english: "Sanskrit",  native: "संस्कृतम्"     },
];

/* Translation dictionary. English is the source of truth. */
type Dict = Record<string, string>;
const T: Record<LangCode, Dict> = {
  en: {
    /* Top nav */
    "nav.search":               "Search",
    "nav.notifications":        "Notifications",
    "nav.account":              "Account & profile",
    "nav.language":             "Language",
    "nav.claims":               "Claims",
    "nav.tpaPortal":            "TPA Portal",
    "nav.analytics":            "Analytics",
    "nav.admin":                "Admin",

    /* Profile card */
    "profile.myProfile":        "My profile",
    "profile.density":          "Density",
    "profile.shortcuts":        "Keyboard shortcuts",
    "profile.preferences":      "Preferences",
    "profile.signOut":          "Sign out",
    "profile.adminConsole":     "Admin console",
    "profile.usersAndRoles":    "Users & roles",
    "profile.integrations":     "Integrations",
    "profile.organisation":     "Organisation",
    "profile.hub":              "Hub",
    "profile.primaryRole":      "Primary role",
    "profile.inView":           "In view",
    "profile.approved":         "Approved",
    "profile.slaBreaches":      "SLA breaches",
    "profile.comfortable":      "Comfortable",
    "profile.compact":          "Compact",

    /* Sidebar / queue */
    "queue.title":              "Claims Queue",
    "queue.subtitle":           "Intake & Review Pipeline",
    "queue.searchPlaceholder":  "Search by patient, policy, file…",
    "queue.filter.all":         "All",
    "queue.filter.processing":  "Processing",
    "queue.filter.ready":       "Ready",
    "queue.filter.submitted":   "Submitted",
    "queue.filter.action":      "Action",
    "queue.filter.failed":      "Failed",
    "queue.empty":              "No claims yet",
    "queue.emptyHint":          "Upload documents to get started",

    /* Drop zone */
    "drop.title":               "Drop claim documents",
    "drop.or":                  "or click to browse",
    "drop.hint":                "Multiple files supported · PDF, Images, Word, Excel, CSV, Text — up to 50 MB each",

    /* Filters / heading bar */
    "header.allClaims":         "All Claims",
    "header.inProcessing":      "In Processing",
    "header.readyForReview":    "Ready for Review",
    "header.actionRequired":    "Action Required",

    /* Common actions */
    "action.send":              "Send",
    "action.cancel":            "Cancel",
    "action.save":              "Save",
    "action.delete":            "Delete",
    "action.upload":            "Upload",
    "action.approve":           "Approve",
    "action.reject":            "Reject",
    "action.sendBack":          "Send back",
    "action.submit":            "Submit",
    "action.viewAll":           "View all",
    "action.close":             "Close",

    /* Workspace / chat */
    "workspace.title":          "Claims Workspace",
    "chat.placeholderActive":   "Ask about this claim — codes, risk, compliance…",
    "chat.placeholderIdle":     "Ask ClaimGPT — ICD-10, CPT, risk analysis, compliance…",
    "chat.processing":          "Processing query…",
    "chat.hint":                "AI-assisted review — always verify codes and amounts before submission.",

    /* Notifications */
    "notif.title":              "Notifications",
    "notif.empty":              "You're all caught up",
    "notif.viewAll":            "View all action items →",
    "notif.updates":            "updates",

    /* SSO */
    "sso.signIn":               "Sign in to ClaimGPT",
    "sso.headline":             "AI-powered claims processing for India.",
    "sso.workEmail":            "Work email",
    "sso.continue":             "Continue",
    "sso.bullet.languages":     "Available in 14 languages — including Hindi, Bengali, Tamil & Telugu",
    "sso.choose":               "Choose your organization's identity provider to continue.",
    "sso.orSignIn":             "or sign in with",

    "lang.changedTo":           "Language changed to",
  },
  hi: {
    /* Top nav */
    "nav.search":               "खोजें",
    "nav.notifications":        "सूचनाएँ",
    "nav.account":              "खाता और प्रोफ़ाइल",
    "nav.language":             "भाषा",
    "nav.claims":               "दावे",
    "nav.tpaPortal":            "TPA पोर्टल",
    "nav.analytics":            "विश्लेषण",
    "nav.admin":                "व्यवस्थापक",

    /* Profile */
    "profile.myProfile":        "मेरी प्रोफ़ाइल",
    "profile.density":          "घनत्व",
    "profile.shortcuts":        "कीबोर्ड शॉर्टकट",
    "profile.preferences":      "वरीयताएँ",
    "profile.signOut":          "साइन आउट",
    "profile.adminConsole":     "व्यवस्थापक कंसोल",
    "profile.usersAndRoles":    "उपयोगकर्ता और भूमिकाएँ",
    "profile.integrations":     "एकीकरण",
    "profile.organisation":     "संस्था",
    "profile.hub":              "केंद्र",
    "profile.primaryRole":      "मुख्य भूमिका",
    "profile.inView":           "देखे गए",
    "profile.approved":         "स्वीकृत",
    "profile.slaBreaches":      "SLA उल्लंघन",
    "profile.comfortable":      "आरामदायक",
    "profile.compact":          "संक्षिप्त",

    /* Queue */
    "queue.title":              "दावा कतार",
    "queue.subtitle":           "इनटेक और समीक्षा पाइपलाइन",
    "queue.searchPlaceholder":  "रोगी, पॉलिसी, फ़ाइल से खोजें…",
    "queue.filter.all":         "सभी",
    "queue.filter.processing":  "प्रसंस्करण",
    "queue.filter.ready":       "तैयार",
    "queue.filter.submitted":   "जमा किया",
    "queue.filter.action":      "कार्रवाई",
    "queue.filter.failed":      "विफल",
    "queue.empty":              "अभी कोई दावा नहीं",
    "queue.emptyHint":          "शुरू करने के लिए दस्तावेज़ अपलोड करें",

    /* Drop zone */
    "drop.title":               "दावा दस्तावेज़ छोड़ें",
    "drop.or":                  "या ब्राउज़ करने के लिए क्लिक करें",
    "drop.hint":                "एकाधिक फ़ाइलें समर्थित · PDF, छवि, Word, Excel, CSV, टेक्स्ट — प्रत्येक 50 MB तक",

    /* Header */
    "header.allClaims":         "सभी दावे",
    "header.inProcessing":      "प्रसंस्करण में",
    "header.readyForReview":    "समीक्षा के लिए तैयार",
    "header.actionRequired":    "कार्रवाई आवश्यक",

    /* Actions */
    "action.send":              "भेजें",
    "action.cancel":            "रद्द करें",
    "action.save":              "सहेजें",
    "action.delete":            "हटाएँ",
    "action.upload":            "अपलोड",
    "action.approve":           "स्वीकृत करें",
    "action.reject":            "अस्वीकार करें",
    "action.sendBack":          "वापस भेजें",
    "action.submit":            "जमा करें",
    "action.viewAll":           "सब देखें",
    "action.close":             "बंद करें",

    /* Workspace */
    "workspace.title":          "दावा कार्यक्षेत्र",
    "chat.placeholderActive":   "इस दावे के बारे में पूछें — कोड, जोखिम, अनुपालन…",
    "chat.placeholderIdle":     "ClaimGPT से पूछें — ICD-10, CPT, जोखिम विश्लेषण, अनुपालन…",
    "chat.processing":          "प्रश्न संसाधित हो रहा है…",
    "chat.hint":                "AI-सहायक समीक्षा — कोड और राशि की जाँच अवश्य करें।",

    /* Notifications */
    "notif.title":              "सूचनाएँ",
    "notif.empty":              "आप सभी अपडेट देख चुके हैं",
    "notif.viewAll":            "सभी कार्रवाई आइटम देखें →",
    "notif.updates":            "अपडेट",

    /* SSO */
    "sso.signIn":               "ClaimGPT में साइन इन करें",
    "sso.headline":             "भारत के लिए AI-संचालित क्लेम प्रसंस्करण।",
    "sso.workEmail":            "कार्य ईमेल",
    "sso.continue":             "जारी रखें",
    "sso.bullet.languages":     "14 भाषाओं में उपलब्ध — हिन्दी, बांग्ला, तमिल और तेलुगू सहित",
    "sso.choose":               "जारी रखने के लिए अपने संगठन का पहचान प्रदाता चुनें।",
    "sso.orSignIn":             "या इनसे साइन इन करें",

    "lang.changedTo":           "भाषा बदली गई",
  },
  bn: {
    "nav.search":          "অনুসন্ধান",
    "nav.notifications":   "বিজ্ঞপ্তি",
    "nav.account":         "অ্যাকাউন্ট ও প্রোফাইল",
    "nav.language":        "ভাষা",
    "nav.claims":          "দাবি",
    "nav.tpaPortal":       "TPA পোর্টাল",
    "nav.analytics":       "বিশ্লেষণ",
    "nav.admin":           "প্রশাসন",
    "profile.myProfile":   "আমার প্রোফাইল",
    "profile.signOut":     "সাইন আউট",
    "profile.preferences": "পছন্দসমূহ",
    "profile.shortcuts":   "কীবোর্ড শর্টকাট",
    "profile.density":     "ঘনত্ব",
    "queue.title":         "দাবি সারি",
    "queue.subtitle":      "ইনটেক ও পর্যালোচনা পাইপলাইন",
    "queue.searchPlaceholder": "রোগী, পলিসি, ফাইল দিয়ে খুঁজুন…",
    "queue.filter.all":         "সকল",
    "queue.filter.processing":  "প্রক্রিয়াকরণ",
    "queue.filter.ready":       "প্রস্তুত",
    "queue.filter.submitted":   "জমা",
    "queue.filter.action":      "কার্য",
    "queue.filter.failed":      "ব্যর্থ",
    "drop.title":          "দাবির নথি এখানে ফেলুন",
    "drop.or":             "অথবা ব্রাউজ করতে ক্লিক করুন",
    "header.allClaims":         "সকল দাবি",
    "header.inProcessing":      "প্রক্রিয়াধীন",
    "header.readyForReview":    "পর্যালোচনার জন্য প্রস্তুত",
    "header.actionRequired":    "কার্য প্রয়োজন",
    "action.send":         "পাঠান",
    "action.cancel":       "বাতিল",
    "action.approve":      "অনুমোদন",
    "action.reject":       "প্রত্যাখ্যান",
    "action.submit":       "জমা দিন",
    "workspace.title":     "দাবি কর্মক্ষেত্র",
    "sso.signIn":          "ClaimGPT-এ সাইন ইন করুন",
    "sso.workEmail":       "কাজের ইমেল",
    "sso.continue":        "চালিয়ে যান",
    "lang.changedTo":      "ভাষা পরিবর্তিত হয়েছে",
  },
  te: {
    "nav.search":          "శోధించండి",
    "nav.notifications":   "నోటిఫికేషన్‌లు",
    "nav.account":         "ఖాతా & ప్రొఫైల్",
    "nav.language":        "భాష",
    "nav.claims":          "క్లెయిమ్‌లు",
    "nav.tpaPortal":       "TPA పోర్టల్",
    "nav.analytics":       "విశ్లేషణలు",
    "nav.admin":           "నిర్వాహకుడు",
    "profile.myProfile":   "నా ప్రొఫైల్",
    "profile.signOut":     "సైన్ అవుట్",
    "profile.preferences": "ప్రాధాన్యతలు",
    "profile.density":     "సాంద్రత",
    "queue.title":         "క్లెయిమ్‌ల క్యూ",
    "queue.subtitle":      "ఇంటేక్ & సమీక్ష పైప్‌లైన్",
    "queue.searchPlaceholder": "రోగి, పాలసీ, ఫైల్ ద్వారా శోధించండి…",
    "queue.filter.all":         "అన్నీ",
    "queue.filter.processing":  "ప్రాసెసింగ్",
    "queue.filter.ready":       "సిద్ధం",
    "queue.filter.submitted":   "సమర్పించబడింది",
    "queue.filter.action":      "చర్య",
    "queue.filter.failed":      "విఫలమైంది",
    "drop.title":          "క్లెయిమ్ పత్రాలను ఇక్కడ వేయండి",
    "drop.or":             "లేదా బ్రౌజ్ చేయడానికి క్లిక్ చేయండి",
    "header.allClaims":         "అన్ని క్లెయిమ్‌లు",
    "header.inProcessing":      "ప్రాసెసింగ్‌లో",
    "header.readyForReview":    "సమీక్షకు సిద్ధం",
    "header.actionRequired":    "చర్య అవసరం",
    "action.send":         "పంపండి",
    "action.cancel":       "రద్దు",
    "action.approve":      "ఆమోదించండి",
    "action.reject":       "తిరస్కరించండి",
    "action.submit":       "సమర్పించండి",
    "workspace.title":     "క్లెయిమ్‌ల వర్క్‌స్పేస్",
    "sso.signIn":          "ClaimGPT లోకి సైన్ ఇన్ చేయండి",
    "sso.workEmail":       "పని ఇమెయిల్",
    "sso.continue":        "కొనసాగించు",
    "lang.changedTo":      "భాష మార్చబడింది",
  },
  mr: {
    "nav.search":          "शोधा",
    "nav.notifications":   "सूचना",
    "nav.account":         "खाते व प्रोफाइल",
    "nav.language":        "भाषा",
    "nav.claims":          "दावे",
    "nav.tpaPortal":       "TPA पोर्टल",
    "nav.analytics":       "विश्लेषण",
    "nav.admin":           "प्रशासक",
    "profile.myProfile":   "माझी प्रोफाइल",
    "profile.signOut":     "साइन आउट",
    "profile.preferences": "प्राधान्ये",
    "profile.density":     "घनता",
    "queue.title":         "दावा रांग",
    "queue.subtitle":      "इनटेक व पुनरावलोकन पाइपलाइन",
    "queue.searchPlaceholder": "रुग्ण, पॉलिसी, फाइलनुसार शोधा…",
    "queue.filter.all":         "सर्व",
    "queue.filter.processing":  "प्रक्रिया",
    "queue.filter.ready":       "तयार",
    "queue.filter.submitted":   "सादर",
    "queue.filter.action":      "कृती",
    "queue.filter.failed":      "अयशस्वी",
    "drop.title":          "दावा कागदपत्रे येथे टाका",
    "drop.or":             "किंवा ब्राउझ करण्यासाठी क्लिक करा",
    "header.allClaims":         "सर्व दावे",
    "header.inProcessing":      "प्रक्रियेत",
    "header.readyForReview":    "पुनरावलोकनासाठी तयार",
    "header.actionRequired":    "कृती आवश्यक",
    "action.send":         "पाठवा",
    "action.cancel":       "रद्द करा",
    "action.approve":      "मंजूर करा",
    "action.reject":       "नाकारा",
    "action.submit":       "सादर करा",
    "workspace.title":     "दावा कार्यक्षेत्र",
    "sso.signIn":          "ClaimGPT मध्ये साइन इन करा",
    "sso.workEmail":       "कार्यालयीन ईमेल",
    "sso.continue":        "पुढे चला",
    "lang.changedTo":      "भाषा बदलली",
  },
  ta: {
    "nav.search":          "தேடுக",
    "nav.notifications":   "அறிவிப்புகள்",
    "nav.account":         "கணக்கு & சுயவிவரம்",
    "nav.language":        "மொழி",
    "nav.claims":          "உரிமைகோரல்கள்",
    "nav.tpaPortal":       "TPA வாயில்",
    "nav.analytics":       "பகுப்பாய்வு",
    "nav.admin":           "நிர்வாகி",
    "profile.myProfile":   "எனது சுயவிவரம்",
    "profile.signOut":     "வெளியேறு",
    "profile.preferences": "விருப்பத்தேர்வுகள்",
    "profile.density":     "அடர்த்தி",
    "queue.title":         "உரிமைகோரல் வரிசை",
    "queue.subtitle":      "உள்ளீடு & மறுஆய்வு பைப்லைன்",
    "queue.searchPlaceholder": "நோயாளி, பாலிசி, கோப்பு மூலம் தேடுக…",
    "queue.filter.all":         "அனைத்தும்",
    "queue.filter.processing":  "செயலாக்கம்",
    "queue.filter.ready":       "தயார்",
    "queue.filter.submitted":   "சமர்ப்பிக்கப்பட்டது",
    "queue.filter.action":      "நடவடிக்கை",
    "queue.filter.failed":      "தோல்வி",
    "drop.title":          "உரிமைகோரல் ஆவணங்களை இங்கே விடவும்",
    "drop.or":             "அல்லது உலாவ கிளிக் செய்யவும்",
    "header.allClaims":         "அனைத்து உரிமைகோரல்கள்",
    "header.inProcessing":      "செயலாக்கத்தில்",
    "header.readyForReview":    "மறுஆய்வுக்கு தயார்",
    "header.actionRequired":    "நடவடிக்கை தேவை",
    "action.send":         "அனுப்புக",
    "action.cancel":       "ரத்து",
    "action.approve":      "ஒப்புதல்",
    "action.reject":       "நிராகரி",
    "action.submit":       "சமர்ப்பி",
    "workspace.title":     "உரிமைகோரல் பணியிடம்",
    "sso.signIn":          "ClaimGPT இல் உள்நுழைக",
    "sso.workEmail":       "வேலை மின்னஞ்சல்",
    "sso.continue":        "தொடரவும்",
    "lang.changedTo":      "மொழி மாற்றப்பட்டது",
  },
  ur: {
    "nav.search":          "تلاش کریں",
    "nav.notifications":   "اطلاعات",
    "nav.account":         "اکاؤنٹ اور پروفائل",
    "nav.language":        "زبان",
    "nav.claims":          "دعوے",
    "nav.tpaPortal":       "TPA پورٹل",
    "nav.analytics":       "تجزیات",
    "nav.admin":           "منتظم",
    "profile.myProfile":   "میری پروفائل",
    "profile.signOut":     "سائن آؤٹ",
    "profile.preferences": "ترجیحات",
    "profile.density":     "کثافت",
    "queue.title":         "دعوہ قطار",
    "queue.subtitle":      "وصول و جائزہ پائپ لائن",
    "queue.searchPlaceholder": "مریض، پالیسی، فائل سے تلاش کریں…",
    "queue.filter.all":         "تمام",
    "queue.filter.processing":  "پروسیسنگ",
    "queue.filter.ready":       "تیار",
    "queue.filter.submitted":   "جمع",
    "queue.filter.action":      "کارروائی",
    "queue.filter.failed":      "ناکام",
    "drop.title":          "دعوہ دستاویزات یہاں چھوڑیں",
    "drop.or":             "یا براؤز کرنے کے لیے کلک کریں",
    "header.allClaims":         "تمام دعوے",
    "header.inProcessing":      "پروسیسنگ میں",
    "header.readyForReview":    "جائزے کے لیے تیار",
    "header.actionRequired":    "کارروائی درکار",
    "action.send":         "بھیجیں",
    "action.cancel":       "منسوخ",
    "action.approve":      "منظور",
    "action.reject":       "مسترد",
    "action.submit":       "جمع کریں",
    "workspace.title":     "دعوہ ورک اسپیس",
    "sso.signIn":          "ClaimGPT میں سائن ان کریں",
    "sso.workEmail":       "کام کی ای میل",
    "sso.continue":        "جاری رکھیں",
    "lang.changedTo":      "زبان تبدیل ہو گئی",
  },
  gu: {
    "nav.search":          "શોધો",
    "nav.notifications":   "સૂચનાઓ",
    "nav.account":         "એકાઉન્ટ અને પ્રોફાઇલ",
    "nav.language":        "ભાષા",
    "nav.claims":          "દાવા",
    "nav.tpaPortal":       "TPA પોર્ટલ",
    "nav.analytics":       "વિશ્લેષણ",
    "nav.admin":           "વ્યવસ્થાપક",
    "profile.myProfile":   "મારી પ્રોફાઇલ",
    "profile.signOut":     "સાઇન આઉટ",
    "queue.title":         "દાવા કતાર",
    "queue.subtitle":      "ઇનટેક અને સમીક્ષા પાઇપલાઇન",
    "queue.filter.all":         "બધા",
    "queue.filter.processing":  "પ્રોસેસિંગ",
    "queue.filter.ready":       "તૈયાર",
    "queue.filter.submitted":   "સબમિટ",
    "queue.filter.action":      "પગલાં",
    "queue.filter.failed":      "નિષ્ફળ",
    "header.allClaims":         "બધા દાવા",
    "header.actionRequired":    "પગલાં જરૂરી",
    "action.send":         "મોકલો",
    "action.approve":      "મંજૂર કરો",
    "action.reject":       "નકારો",
    "sso.signIn":          "ClaimGPT માં સાઇન ઇન કરો",
    "sso.workEmail":       "કાર્ય ઈમેઇલ",
    "sso.continue":        "ચાલુ રાખો",
    "lang.changedTo":      "ભાષા બદલાઈ",
  },
  kn: {
    "nav.search":          "ಹುಡುಕಿ",
    "nav.notifications":   "ಅಧಿಸೂಚನೆಗಳು",
    "nav.account":         "ಖಾತೆ ಮತ್ತು ಪ್ರೊಫೈಲ್",
    "nav.language":        "ಭಾಷೆ",
    "nav.claims":          "ಕ್ಲೈಮ್‌ಗಳು",
    "nav.tpaPortal":       "TPA ಪೋರ್ಟಲ್",
    "nav.analytics":       "ವಿಶ್ಲೇಷಣೆ",
    "nav.admin":           "ನಿರ್ವಾಹಕ",
    "profile.myProfile":   "ನನ್ನ ಪ್ರೊಫೈಲ್",
    "profile.signOut":     "ಸೈನ್ ಔಟ್",
    "queue.title":         "ಕ್ಲೈಮ್ ಸಾಲು",
    "queue.subtitle":      "ಪ್ರವೇಶ ಮತ್ತು ಪರಿಶೀಲನೆ ಪೈಪ್‌ಲೈನ್",
    "queue.filter.all":         "ಎಲ್ಲಾ",
    "queue.filter.processing":  "ಪ್ರಕ್ರಿಯೆ",
    "queue.filter.ready":       "ಸಿದ್ಧ",
    "queue.filter.submitted":   "ಸಲ್ಲಿಸಲಾಗಿದೆ",
    "queue.filter.action":      "ಕ್ರಮ",
    "queue.filter.failed":      "ವಿಫಲ",
    "header.allClaims":         "ಎಲ್ಲಾ ಕ್ಲೈಮ್‌ಗಳು",
    "header.actionRequired":    "ಕ್ರಮ ಅಗತ್ಯ",
    "action.send":         "ಕಳುಹಿಸಿ",
    "action.approve":      "ಅನುಮೋದಿಸಿ",
    "action.reject":       "ತಿರಸ್ಕರಿಸಿ",
    "sso.signIn":          "ClaimGPT ಗೆ ಸೈನ್ ಇನ್ ಮಾಡಿ",
    "sso.workEmail":       "ಕೆಲಸದ ಇಮೇಲ್",
    "sso.continue":        "ಮುಂದುವರಿಯಿರಿ",
    "lang.changedTo":      "ಭಾಷೆ ಬದಲಾಗಿದೆ",
  },
  or: {
    "nav.search":          "ସନ୍ଧାନ କରନ୍ତୁ",
    "nav.notifications":   "ବିଜ୍ଞପ୍ତି",
    "nav.account":         "ଆକାଉଣ୍ଟ ଓ ପ୍ରୋଫାଇଲ",
    "nav.language":        "ଭାଷା",
    "nav.claims":          "ଦାବି",
    "nav.tpaPortal":       "TPA ପୋର୍ଟାଲ",
    "nav.analytics":       "ବିଶ୍ଳେଷଣ",
    "nav.admin":           "ପ୍ରଶାସକ",
    "profile.myProfile":   "ମୋର ପ୍ରୋଫାଇଲ",
    "profile.signOut":     "ସାଇନ ଆଉଟ",
    "queue.title":         "ଦାବି କ୍ୟୁ",
    "queue.filter.all":         "ସବୁ",
    "queue.filter.processing":  "ପ୍ରକ୍ରିୟାକରଣ",
    "queue.filter.ready":       "ପ୍ରସ୍ତୁତ",
    "queue.filter.submitted":   "ଦାଖଲ",
    "queue.filter.action":      "କାର୍ଯ୍ୟ",
    "queue.filter.failed":      "ବିଫଳ",
    "header.allClaims":         "ସମସ୍ତ ଦାବି",
    "header.actionRequired":    "କାର୍ଯ୍ୟ ଆବଶ୍ୟକ",
    "action.send":         "ପଠାନ୍ତୁ",
    "action.approve":      "ଅନୁମୋଦନ କରନ୍ତୁ",
    "action.reject":       "ପ୍ରତ୍ୟାଖ୍ୟାନ କରନ୍ତୁ",
    "sso.signIn":          "ClaimGPT ରେ ସାଇନ ଇନ କରନ୍ତୁ",
    "sso.workEmail":       "କାର୍ଯ୍ୟ ଇମେଲ",
    "sso.continue":        "ଆଗକୁ ବଢ଼ନ୍ତୁ",
    "lang.changedTo":      "ଭାଷା ବଦଳାଗଲା",
  },
  pa: {
    "nav.search":          "ਖੋਜੋ",
    "nav.notifications":   "ਸੂਚਨਾਵਾਂ",
    "nav.account":         "ਖਾਤਾ ਤੇ ਪ੍ਰੋਫਾਈਲ",
    "nav.language":        "ਭਾਸ਼ਾ",
    "nav.claims":          "ਦਾਅਵੇ",
    "nav.tpaPortal":       "TPA ਪੋਰਟਲ",
    "nav.analytics":       "ਵਿਸ਼ਲੇਸ਼ਣ",
    "nav.admin":           "ਪ੍ਰਬੰਧਕ",
    "profile.myProfile":   "ਮੇਰੀ ਪ੍ਰੋਫਾਈਲ",
    "profile.signOut":     "ਸਾਈਨ ਆਊਟ",
    "queue.title":         "ਦਾਅਵਾ ਕਤਾਰ",
    "queue.filter.all":         "ਸਾਰੇ",
    "queue.filter.processing":  "ਪ੍ਰੋਸੈਸਿੰਗ",
    "queue.filter.ready":       "ਤਿਆਰ",
    "queue.filter.submitted":   "ਜਮ੍ਹਾਂ",
    "queue.filter.action":      "ਕਾਰਵਾਈ",
    "queue.filter.failed":      "ਅਸਫਲ",
    "header.allClaims":         "ਸਾਰੇ ਦਾਅਵੇ",
    "header.actionRequired":    "ਕਾਰਵਾਈ ਲੋੜੀਂਦੀ",
    "action.send":         "ਭੇਜੋ",
    "action.approve":      "ਮਨਜ਼ੂਰ ਕਰੋ",
    "action.reject":       "ਅਸਵੀਕਾਰ ਕਰੋ",
    "sso.signIn":          "ClaimGPT ਵਿੱਚ ਸਾਈਨ ਇਨ ਕਰੋ",
    "sso.workEmail":       "ਕੰਮ ਦੀ ਈਮੇਲ",
    "sso.continue":        "ਜਾਰੀ ਰੱਖੋ",
    "lang.changedTo":      "ਭਾਸ਼ਾ ਬਦਲੀ ਗਈ",
  },
  ml: {
    "nav.search":          "തിരയുക",
    "nav.notifications":   "അറിയിപ്പുകൾ",
    "nav.account":         "അക്കൗണ്ട് & പ്രൊഫൈൽ",
    "nav.language":        "ഭാഷ",
    "nav.claims":          "ക്ലെയിമുകൾ",
    "nav.tpaPortal":       "TPA പോർട്ടൽ",
    "nav.analytics":       "വിശകലനം",
    "nav.admin":           "അഡ്മിൻ",
    "profile.myProfile":   "എന്റെ പ്രൊഫൈൽ",
    "profile.signOut":     "സൈൻ ഔട്ട്",
    "queue.title":         "ക്ലെയിം ക്യൂ",
    "queue.filter.all":         "എല്ലാം",
    "queue.filter.processing":  "പ്രോസസ്സിംഗ്",
    "queue.filter.ready":       "തയ്യാർ",
    "queue.filter.submitted":   "സമർപ്പിച്ചു",
    "queue.filter.action":      "നടപടി",
    "queue.filter.failed":      "പരാജയം",
    "header.allClaims":         "എല്ലാ ക്ലെയിമുകളും",
    "header.actionRequired":    "നടപടി ആവശ്യം",
    "action.send":         "അയയ്ക്കുക",
    "action.approve":      "അംഗീകരിക്കുക",
    "action.reject":       "നിരസിക്കുക",
    "sso.signIn":          "ClaimGPT-ലേക്ക് സൈൻ ഇൻ ചെയ്യുക",
    "sso.workEmail":       "ജോലി ഇമെയിൽ",
    "sso.continue":        "തുടരുക",
    "lang.changedTo":      "ഭാഷ മാറ്റി",
  },
  as: {
    "nav.search":          "সন্ধান কৰক",
    "nav.notifications":   "জাননী",
    "nav.account":         "একাউণ্ট আৰু প্ৰফাইল",
    "nav.language":        "ভাষা",
    "nav.claims":          "দাবী",
    "nav.tpaPortal":       "TPA পৰ্টেল",
    "nav.analytics":       "বিশ্লেষণ",
    "nav.admin":           "প্ৰশাসক",
    "profile.myProfile":   "মোৰ প্ৰফাইল",
    "profile.signOut":     "ছাইন আউট",
    "queue.title":         "দাবী শাৰী",
    "queue.filter.all":         "সকলো",
    "queue.filter.processing":  "প্ৰক্ৰিয়াকৰণ",
    "queue.filter.ready":       "সাজু",
    "queue.filter.submitted":   "জমা",
    "queue.filter.action":      "কাৰ্য",
    "queue.filter.failed":      "ব্যৰ্থ",
    "header.allClaims":         "সকলো দাবী",
    "header.actionRequired":    "কাৰ্য প্ৰয়োজন",
    "action.send":         "পঠিয়াওক",
    "action.approve":      "অনুমোদন কৰক",
    "action.reject":       "প্ৰত্যাখ্যান কৰক",
    "sso.signIn":          "ClaimGPT-ত ছাইন ইন কৰক",
    "sso.workEmail":       "কাৰ্যালয়ৰ ইমেইল",
    "sso.continue":        "অব্যাহত ৰাখক",
    "lang.changedTo":      "ভাষা সলনি কৰা হ’ল",
  },
  sa: {
    "nav.search":          "अन्वेषणम्",
    "nav.notifications":   "सूचनाः",
    "nav.account":         "खातम् च प्रोफाइलम्",
    "nav.language":        "भाषा",
    "nav.claims":          "दावाः",
    "nav.tpaPortal":       "TPA द्वारम्",
    "nav.analytics":       "विश्लेषणम्",
    "nav.admin":           "व्यवस्थापकः",
    "profile.myProfile":   "मम प्रोफाइलम्",
    "profile.signOut":     "निष्क्रमणम्",
    "queue.title":         "दावा-पङ्क्तिः",
    "queue.filter.all":         "सर्वे",
    "queue.filter.processing":  "प्रसंस्करणम्",
    "queue.filter.ready":       "सज्जः",
    "queue.filter.submitted":   "समर्पितम्",
    "queue.filter.action":      "क्रिया",
    "queue.filter.failed":      "विफलम्",
    "header.allClaims":         "सर्वे दावाः",
    "header.actionRequired":    "क्रिया आवश्यकी",
    "action.send":         "प्रेषयतु",
    "action.approve":      "अनुमोदयतु",
    "action.reject":       "अस्वीकरोतु",
    "sso.signIn":          "ClaimGPT-मध्ये प्रवेशं कुरुत",
    "sso.workEmail":       "कार्य-ईमेलः",
    "sso.continue":        "प्रचलतु",
    "lang.changedTo":      "भाषा परिवर्तिता",
  },
};

const STORAGE_KEY = "claimgpt.lang";
const DEFAULT_LANG: LangCode = "en";

interface I18nCtx {
  lang: LangCode;
  meta: LanguageMeta;
  setLang: (code: LangCode) => void;
  t: (key: string, fallback?: string) => string;
  languages: LanguageMeta[];
}

const Ctx = createContext<I18nCtx | null>(null);

export function LanguageProvider({ children }: { children: React.ReactNode }) {
  const [lang, setLangState] = useState<LangCode>(DEFAULT_LANG);

  /* Restore on mount (client-only). */
  useEffect(() => {
    try {
      const stored = localStorage.getItem(STORAGE_KEY) as LangCode | null;
      if (stored && LANGUAGES.some((l) => l.code === stored)) {
        setLangState(stored);
      }
    } catch { /* localStorage may be blocked */ }
  }, []);

  /* Reflect onto <html> attributes for native browser handling + CSS hooks. */
  useEffect(() => {
    if (typeof document === "undefined") return;
    const meta = LANGUAGES.find((l) => l.code === lang) || LANGUAGES[0];
    document.documentElement.setAttribute("lang", lang);
    document.documentElement.setAttribute("dir", meta.rtl ? "rtl" : "ltr");
  }, [lang]);

  const setLang = useCallback((code: LangCode) => {
    setLangState(code);
    try { localStorage.setItem(STORAGE_KEY, code); } catch { /* ignore */ }
  }, []);

  const t = useCallback((key: string, fallback?: string) => {
    return T[lang]?.[key] ?? T.en[key] ?? fallback ?? key;
  }, [lang]);

  const value = useMemo<I18nCtx>(() => ({
    lang,
    meta: LANGUAGES.find((l) => l.code === lang) || LANGUAGES[0],
    setLang,
    t,
    languages: LANGUAGES,
  }), [lang, setLang, t]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useI18n(): I18nCtx {
  const ctx = useContext(Ctx);
  if (!ctx) {
    /* Tolerant fallback for components rendered outside provider (e.g. tests). */
    return {
      lang: DEFAULT_LANG,
      meta: LANGUAGES[0],
      setLang: () => {},
      t: (k, f) => T.en[k] ?? f ?? k,
      languages: LANGUAGES,
    };
  }
  return ctx;
}
