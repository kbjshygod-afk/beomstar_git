// 봉주르 프랑스어 - 학습 데이터 (임시 스텁, 콘텐츠 파이프라인 완료 후 교체 예정)
window.FR_DATA = {
 "app": "봉주르 프랑스어", "version": 0,
 "units": [
  {
   "unitId": 0, "title": "알파벳과 발음 규칙", "subtitle": "쓰는 대로 읽지 않는 언어 정복", "icon": "🔤",
   "lessons": [
    {
     "id": "u0l1", "title": "알파벳과 악센트", "goal": "악센트 부호가 소리를 어떻게 바꾸는지 알 수 있어요.",
     "words": [
      { "fr": "le café", "ko": "커피, 카페", "koPron": "르 카페" },
      { "fr": "l'élève", "ko": "학생", "koPron": "렐레브" },
      { "fr": "être", "ko": "~이다", "koPron": "에트르" },
      { "fr": "français", "ko": "프랑스어", "koPron": "프랑세" },
      { "fr": "Noël", "ko": "크리스마스", "koPron": "노엘" },
      { "fr": "bonjour", "ko": "안녕하세요", "koPron": "봉주르" },
      { "fr": "merci", "ko": "감사합니다", "koPron": "메르시" },
      { "fr": "oui", "ko": "네", "koPron": "위" }
     ],
     "keySentences": [
      { "fr": "Bonjour !", "ko": "안녕하세요!", "koPron": "봉주르" },
      { "fr": "Merci beaucoup.", "ko": "정말 감사합니다.", "koPron": "메르시 보쿠" }
     ],
     "dialogue": {
      "title": "첫 인사", "situation": "수진이 파리에서 처음 인사를 건네요.",
      "turns": [
       { "speaker": "A", "name": "수진", "fr": "Bonjour !", "ko": "안녕하세요!", "koPron": "봉주르" },
       { "speaker": "B", "name": "뤼카", "fr": "Bonjour ! Ça va ?", "ko": "안녕하세요! 잘 지내요?", "koPron": "봉주르 사 바" }
      ]
     },
     "grammar": [
      { "title": "악센트가 소리를 바꿔요", "explain": "e는 '으'지만, é는 '에'로 또렷하게 소리 나요. è·ê도 '에'예요.",
        "examples": [{ "fr": "le café", "ko": "커피", "koPron": "르 카페" }] }
     ],
     "tips": ["ç(세디유)는 언제나 'ㅅ' 소리예요. français = 프랑세."],
     "culture": "임시 스텁 콘텐츠입니다. 정식 커리큘럼으로 곧 교체됩니다.",
     "quiz": [
      { "type": "choice", "q": "'안녕하세요'는 프랑스어로?", "choices": ["Bonjour", "Merci", "Au revoir", "Pardon"], "answer": 0, "explain": "Bonjour(봉주르)가 기본 인사예요." },
      { "type": "listen", "q": "들리는 말의 뜻은?", "fr": "Merci", "choices": ["감사합니다", "안녕하세요", "죄송합니다", "안녕히 가세요"], "answer": 0, "explain": "Merci는 '감사합니다'예요." }
     ]
    }
   ]
  }
 ]
};
