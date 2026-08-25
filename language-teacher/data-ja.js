// 곤니치와 일본어 - 학습 데이터 (임시 스텁, 콘텐츠 파이프라인 완료 후 교체 예정)
window.JA_DATA = {
 "app": "곤니치와 일본어", "version": 0,
 "units": [
  {
   "unitId": 0, "title": "히라가나 첫걸음", "subtitle": "가나 기초 정복", "icon": "あ",
   "lessons": [
    {
     "id": "u0l1", "title": "모음 다섯 개", "goal": "히라가나 기본 모음 5개를 읽을 수 있어요.",
     "words": [
      { "ja": "あ", "romaji": "a", "ko": "아", "koPron": "아" },
      { "ja": "い", "romaji": "i", "ko": "이", "koPron": "이" },
      { "ja": "う", "romaji": "u", "ko": "우", "koPron": "우" },
      { "ja": "え", "romaji": "e", "ko": "에", "koPron": "에" },
      { "ja": "お", "romaji": "o", "ko": "오", "koPron": "오" },
      { "ja": "あい", "romaji": "ai", "ko": "사랑", "koPron": "아이" },
      { "ja": "いえ", "romaji": "ie", "ko": "집", "koPron": "이에" },
      { "ja": "うえ", "romaji": "ue", "ko": "위", "koPron": "우에" }
     ],
     "keySentences": [
      { "ja": "こんにちは。", "romaji": "Konnichiwa.", "ko": "안녕하세요.", "koPron": "곤니치와" },
      { "ja": "ありがとう。", "romaji": "Arigatou.", "ko": "고마워요.", "koPron": "아리가토" }
     ],
     "dialogue": {
      "title": "첫 인사", "situation": "수진이 일본인 친구를 처음 만났어요.",
      "turns": [
       { "speaker": "A", "name": "수진", "ja": "こんにちは！", "romaji": "Konnichiwa!", "ko": "안녕하세요!", "koPron": "곤니치와" },
       { "speaker": "B", "name": "유이", "ja": "こんにちは！よろしく。", "romaji": "Konnichiwa! Yoroshiku.", "ko": "안녕하세요! 잘 부탁해요.", "koPron": "곤니치와 요로시쿠" }
      ]
     },
     "grammar": [
      { "title": "히라가나는 소리 문자", "explain": "히라가나는 한 글자가 하나의 소리를 나타내요. あ는 항상 '아'로만 읽혀요.",
        "examples": [{ "ja": "あお", "romaji": "ao", "ko": "파랑", "koPron": "아오" }] }
     ],
     "tips": ["모음 5개(あいうえお)만 정확히 외우면 나머지 글자는 자음+모음 조합이라 훨씬 쉬워요."],
     "culture": "임시 스텁 콘텐츠입니다. 정식 커리큘럼으로 곧 교체됩니다.",
     "quiz": [
      { "type": "choice", "q": "'안녕하세요'는 일본어로?", "choices": ["こんにちは", "ありがとう", "さようなら", "すみません"], "answer": 0, "explain": "こんにちは(곤니치와)가 낮 인사예요." },
      { "type": "listen", "q": "들리는 글자는?", "ja": "あ", "choices": ["a", "i", "u", "e"], "answer": 0, "explain": "あ는 '아'로 읽어요." }
     ]
    }
   ]
  }
 ]
};
