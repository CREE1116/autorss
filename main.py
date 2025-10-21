import os
import json
import feedparser
from google import genai
from datetime import datetime
import tweepy
import time
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# --- CONFIGURATION ---
# Get API keys and other configurations from environment variables
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY")
# Twitter
TWITTER_API_KEY = os.environ.get("TWITTER_API_KEY")
TWITTER_API_SECRET = os.environ.get("TWITTER_API_SECRET")
TWITTER_ACCESS_TOKEN = os.environ.get("TWITTER_ACCESS_TOKEN")
TWITTER_ACCESS_TOKEN_SECRET = os.environ.get("TWITTER_ACCESS_TOKEN_SECRET")

# The new RSS feed URL provided by the user
RSS_URL = "https://tldr.takara.ai/api/papers"
PROCESSED_POSTS_FILE = "processed_posts.txt"

def get_latest_posts():
    """Fetches and parses the RSS feed."""
    print(f"Fetching RSS feed from {RSS_URL}...")
    feed = feedparser.parse(RSS_URL)
    return feed.entries

def summarize_with_gemini(original_summary, title, link, date):
    """Summarizes content for Twitter using the Gemini API."""
    print("Re-summarizing with Gemini for Twitter...")
    
    prompt = f'''Role: You are an AI-powered tech curator. Your task is to create a Twitter thread from the following content. The post should be in Korean.

Read the content, then generate a JSON object with a single key: "twitter_thread".

- "twitter_thread": An array of strings, where each string is a tweet for a Twitter thread.

Rules for Twitter:
- Each tweet must be less than 280 characters.
- The first tweet must be in the format: "오늘의 AI 논문 ({date}): {title}\n\n{link}".
- The last tweet must include the hashtags "#AI #ML #논문요약".
- Add a thread indicator like (1/n) to each tweet.

Content to summarize:
{original_summary}

Return ONLY the JSON object. Do not add ```json markdown.
'''
    
    for i in range(3): # Retry up to 3 times
        try:
            client = genai.Client()
            response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt
            )

            if not response.text:
                if response.prompt_feedback and response.prompt_feedback.block_reason:
                     print(f"Error: Gemini API response was blocked due to {response.prompt_feedback.block_reason}")
                else:
                    print("Error: Gemini API returned an empty response.")
                continue
            
            # Find the start and end of the JSON object
            json_start = response.text.find('{')
            json_end = response.text.rfind('}')
            
            if json_start == -1 or json_end == -1:
                print(f"Error: Could not find JSON object in Gemini response (try {i+1}/3).")
                print(f"Invalid response: {response.text}")
                continue

            json_string = response.text[json_start:json_end+1]
            return json.loads(json_string)

        except json.JSONDecodeError as e:
            print(f"Gemini 요약 중 JSON 파싱 에러 발생 (시도 {i+1}/3): {e}")
            if 'response' in locals():
                print(f"잘못된 응답: {response.text}")
        except Exception as e:
            print(f"Gemini 요약 중 에러 발생 (시도 {i+1}/3): {e}")
        
        if i < 2:
            print("2초 후 재시도합니다...")
            time.sleep(2) 

    return None

def post_to_twitter(tweet_thread):
    """Posts the given thread to X (Twitter)."""
    print("Attempting to post thread to Twitter...")
    if not all([TWITTER_API_KEY, TWITTER_API_SECRET, TWITTER_ACCESS_TOKEN, TWITTER_ACCESS_TOKEN_SECRET]):
        print("에러: 트위터 API 키 환경 변수가 모두 설정되지 않았습니다.")
        return
    try:
        client = tweepy.Client(
            consumer_key=TWITTER_API_KEY,
            consumer_secret=TWITTER_API_SECRET,
            access_token=TWITTER_ACCESS_TOKEN,
            access_token_secret=TWITTER_ACCESS_TOKEN_SECRET
        )
        
        last_tweet_id = None
        for i, tweet_text in enumerate(tweet_thread):
            print(f"Posting tweet {i+1}/{len(tweet_thread)}...")
            if last_tweet_id:
                response = client.create_tweet(text=tweet_text, in_reply_to_tweet_id=last_tweet_id)
            else:
                response = client.create_tweet(text=tweet_text)
            
            last_tweet_id = response.data['id']
            print(f"  > Tweet posted: https://x.com/user/status/{last_tweet_id}")

        print("Successfully posted thread to Twitter.")
        return True
    except Exception as e:
        print(f"Twitter에 포스팅 중 에러 발생: {e}")
        return False

def load_processed_posts():
    """Loads the set of already processed post URLs."""
    if not os.path.exists(PROCESSED_POSTS_FILE):
        return set()
    with open(PROCESSED_POSTS_FILE, "r") as f:
        return set(line.strip() for line in f)

def save_processed_post(url):
    """Saves a new post URL to the processed list."""
    with open(PROCESSED_POSTS_FILE, "a") as f:
        f.write(url + "\n")

def main():
    """Main function to run the bot."""
    if not GOOGLE_API_KEY:
        print("에러: GOOGLE_API_KEY 환경 변수가 설정되지 않았습니다.")
        return

    print("AutoRSS 봇을 시작합니다...")
    today_date = datetime.now().strftime("%Y-%m-%d")
    processed_posts = load_processed_posts()
    posts = get_latest_posts()

    for post in posts:
        post_id = post.get('id', post.link)
        if post_id not in processed_posts:
            print(f"새로운 논문 발견: {post.title}")
            
            original_summary = post.get('summary')
            if not original_summary:
                print("요약 정보가 없어 건너뜁니다.")
                continue

            social_posts = summarize_with_gemini(original_summary, post.title, post.link, today_date)
            if not social_posts:
                print("Gemini 요약에 최종 실패하여 다음으로 넘어갑니다.")
                continue
            
            twitter_thread = social_posts.get("twitter_thread")

            if twitter_thread:
                twitter_post_successful = post_to_twitter(twitter_thread)
                if twitter_post_successful:
                    save_processed_post(post_id)
                    print(f"포스트 처리 완료: {post.title}")
                else:
                    print(f"Twitter 포스팅 실패: {post.title} (processed_posts.txt에 저장하지 않음)")
            else:
                print("트위터 스레드가 없어 포스팅을 건너뜁니다.")
                save_processed_post(post_id) # 트위터 스레드가 없어도 처리된 것으로 간주
            
            # 한 번에 하나의 포스트만 처리하고 종료
            break
    
    print("봇 실행 완료.")

if __name__ == "__main__":
    main()
