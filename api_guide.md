Using Gemini 2.5 Flash on Google Cloud for Short-Form Video Attraction Analysis
Introduction
Gemini 2.5 Flash Overview: Gemini 2.5 Flash is Google’s latest multimodal generative AI model available through Vertex AI. It’s a “thinking” model that balances high performance with cost-efficiency, accepting text, images, audio, and video as inputs and producing text outputs
ai.google.dev
. In practice, this means you can feed Gemini 2.5 Flash a short video clip (with audio) and get a text analysis in response. It supports advanced reasoning (“hybrid reasoning”) with configurable thinking steps for complex tasks
developers.googleblog.com
, but also delivers fast responses for simpler prompts. Use Case – Extracting Attractions from Videos: In this guide, we’ll show how to use Gemini 2.5 Flash to analyze short-form videos (e.g. Instagram Reels or TikToks) and extract any attractions mentioned or shown, such as landmarks, restaurants, or cultural sites. For example, given a travel reel, the model can identify places like Central Park, Eiffel Tower, or Local Cafe X mentioned in speech or visible in the footage. We will demonstrate how to set up the environment, upload and preprocess videos, prompt the model (with structured output), use Google Search grounding for enriched details, and handle the results.
Environment Setup
Prerequisites:
Google Cloud Project: You need a Google Cloud project with billing enabled and the Vertex AI API activated. Enable the Vertex AI API in the Cloud Console or via CLI (e.g. gcloud services enable aiplatform.googleapis.com). This provides access to Generative AI Studio and the Vertex AI endpoints for Gemini.
Accept Vertex AI Terms: If this is your first time using Vertex AI Generative AI, you may need to accept terms in the console. Also, to use Google Search grounding (discussed later), you must enable Google Search suggestions and agree to display requirements
ai.google.dev
. This is usually done via the Vertex AI Studio UI when first toggling the feature.
APIs for Preprocessing (optional): If you plan to preprocess videos (for example, transcribe audio or detect text in frames), enable relevant APIs like Cloud Video Intelligence API (for speech transcription
cloud.google.com
 or shot detection) or Cloud Vision API (for image/landmark recognition). These are optional because Gemini itself can handle multimodal input, but they can improve accuracy or efficiency.
SDKs and Tools: We will use Python for the examples. Set up the following:
Google Cloud SDK: Install and authenticate the Google Cloud CLI (gcloud auth login and set your project). This ensures you can obtain credentials for API calls or use gcloud for deployment.
Vertex AI GenAI SDK (google-genai): This is the recommended SDK for calling generative models. Install it with pip:
pip install --upgrade google-genai
After installing, set environment variables so it knows to use Vertex AI:
export GOOGLE_CLOUD_PROJECT="<YOUR_PROJECT_ID>"
export GOOGLE_CLOUD_LOCATION="global"
export GOOGLE_GENAI_USE_VERTEXAI=True
These ensure the SDK targets Vertex AI’s endpoints
cloud.google.com
. You can find more details in the [Gen AI SDK reference]
cloud.google.com
.
Google Cloud Storage SDK (google-cloud-storage): This helps upload and download videos from Cloud Storage buckets. Install via pip install google-cloud-storage.
(Optional) Cloud Functions Framework: If writing a Cloud Function in Python to handle video uploads, you might use functions-framework. Otherwise, you can deploy a function directly via gcloud.
Vertex AI Model Access: Gemini 2.5 Flash is in preview, with model ID gemini-2.5-flash-preview-04-17
cloud.google.com
. In the SDK, you can request this model by name. Ensure your account has access (as of 2025, new projects get 2.5 by default since 1.5 is deprecated
cloud.google.com
). No custom model deployment is needed – you will use it via the Vertex AI API directly.
Uploading and Preprocessing Videos
Video Formats & Durations: Gemini 2.5 Flash supports common video formats like MP4, MOV, WebM, WMV, FLV, 3GP and more
cloud.google.com
. For best results, use a widely supported codec (e.g. H.264 MP4). The model can handle videos up to ~45 minutes long with audio
cloud.google.com
cloud.google.com
, but short-form videos (say 30–60 seconds) are well within the limits. Make sure the video’s audio is clear if it contains spoken content, as the model will internally transcribe and analyze it. Uploading to Cloud Storage: Store your videos in a Google Cloud Storage (GCS) bucket so that Vertex AI can access them. You can use the GCP Console to upload, or programmatically with Python:
from google.cloud import storage

bucket_name = "my-video-bucket"
video_path = "reels/paris_day_out.mp4"   # path in the bucket
local_file = "/home/user/paris_day_out.mp4"  # local path to upload

client = storage.Client()
bucket = client.bucket(bucket_name)
blob = bucket.blob(video_path)
blob.upload_from_filename(local_file)
print(f"Uploaded to gs://{bucket_name}/{video_path}")
This uploads paris_day_out.mp4 to the GCS URI gs://my-video-bucket/reels/paris_day_out.mp4. Keep note of the GCS URI, as we’ll supply it to the Gemini API. You may also want to organize an upload trigger: for instance, a Cloud Function that automatically runs analysis when a new video is uploaded. To do that, create a Cloud Function triggered by GCS finalize events on your bucket. The function can read the object name from the event and then invoke the Gemini analysis as described in the next sections. Preprocessing (Optional): In many cases, you can feed the raw video directly to Gemini and let it handle understanding. However, preprocessing can improve results:
Transcription: If the video has speech describing the places, using the Video Intelligence API’s speech transcription feature can give you a text transcript of the audio
cloud.google.com
. This might be more accurate for speech-to-text than the general LLM, especially for proper nouns. You could then feed this transcript to Gemini (instead of or in addition to the video) to focus on language understanding.
Frame Extraction: If the video is mostly visual (no speech), consider extracting key frames (using FFMPEG or Video Intelligence’s shot change detection) and using an image analysis. Gemini can take image inputs too, or you could use the Cloud Vision API to detect landmarks in those frames. For example, Cloud Vision’s landmark detection might recognize the Eiffel Tower in a frame. You could then provide that information to Gemini to verify or get more context.
Text (OCR) Extraction: Short videos often have on-screen text (captions or location names). Using Vision API’s text detection on some frames could capture those names, which you can feed into the prompt. Gemini 2.5 Flash can also directly read text from images, but explicit OCR could ensure nothing is missed.
These steps are optional – Gemini 2.5 Flash is fully multimodal, so you can also simply give it the video file and a well-crafted prompt. In the next section, we’ll assume minimal preprocessing (using the video and perhaps its raw transcript).
Prompting Gemini 2.5 Flash
With your video on GCS, you can now prompt Gemini to identify attractions in it. Prompts are how you instruct the model what to do and how to format its answer. Including Video in the Prompt: When using the GenAI SDK, you can supply a video by using a Part object with the file’s URI and MIME type. For example:
from google import genai
from google.genai.types import Part

client = genai.Client()  # already configured for Vertex AI

video_uri = "gs://my-video-bucket/reels/paris_day_out.mp4"
video_part = Part.from_uri(file_uri=video_uri, mime_type="video/mp4")
This video_part now represents the video content. We will include it in the contents list for the model along with our text prompt. Under the hood, Vertex AI will fetch this video from GCS and provide it to Gemini for analysis
cloud.google.com
. You can include multiple media parts and text parts in one prompt if needed (up to 10 videos per prompt are allowed
cloud.google.com
cloud.google.com
). Crafting the Prompt: Now we write the instruction for the model. We want it to detect any named attractions in the video. A straightforward prompt might be: “What attractions (landmarks, restaurants, or cultural sites) are mentioned or shown in this video?” However, to get a structured response (like JSON), it’s better to explicitly ask for it. For example, we can prompt:
Analyze the video and identify any attractions (landmarks, restaurants, cultural sites) that are either mentioned in the audio or visible in the footage. List each attraction with its name (as precisely as possible). If multiple attractions are present, provide each on a new line.
Initially, you might just get an answer like: “It shows the Eiffel Tower and mentions a cafe called Les Deux Magots.” This is useful, but we can improve format. Let’s refine the prompt to request a JSON output:
Analyze the video and identify any attractions (landmarks, restaurants, or cultural sites) mentioned or shown. Provide the result as a JSON array of objects, where each object has a "name" and "type" (e.g. landmark, restaurant, etc.). Only include actual place names.
By asking for JSON, we guide the model to a structured format. Gemini 2.5 Flash supports structured output generation, especially when the prompt clearly specifies the format. After adding this, an example output might look like:
[
  {
    "name": "Eiffel Tower",
    "type": "landmark"
  },
  {
    "name": "Louvre Museum",
    "type": "landmark"
  },
  {
    "name": "Café de Flore",
    "type": "restaurant"
  }
]
(Example explanation: the video perhaps showed the Eiffel Tower, the exterior of the Louvre, and a scene at Café de Flore.) You can adjust the prompt further to include additional fields or different formatting (even Pydantic model notation if desired), but JSON is generally easiest to parse. Temperature and Parameters: For extraction tasks, it’s often best to use a deterministic setting: e.g. temperature = 0.0 and top-K = 1. This makes the model less creative and more focused, increasing the chance it sticks to factual identification. With these settings, the model will always choose the most likely completion
cloud.google.com
. In our SDK call, we’ll set temperature=0.0. We can also limit max_output_tokens to a small number since we expect only a few names in return (optional). Example SDK Call: Putting it together, here’s how you prompt Gemini with the video and instruction:
from google.genai.types import GenerateContentConfig

prompt_text = (
    "Analyze the video and identify any attractions (landmarks, restaurants, cultural sites) mentioned or shown. "
    "Respond in JSON with an array of {name, type} objects for each attraction."
)

response = client.models.generate_content(
    model="gemini-2.5-flash-preview-04-17",  # specify the 2.5 Flash model
    contents=[ video_part, prompt_text ],
    config=GenerateContentConfig(
        temperature=0.0,
        # You could also set max_output_tokens, etc., here if needed
    )
)
print(response.text)
If all goes well, response.text will contain a JSON string as shown in the example above (or an equivalent structured list of attractions found). Without further grounding, the model is basing its answer on the video content and its own knowledge.
Search Grounding Integration
To enhance accuracy and enrich the details of identified attractions, grounding the model with Google Search is a powerful feature. Grounding means the model can perform web searches in real-time to fetch up-to-date information and incorporate it into its answer
cloud.google.com
. For our use case, this can help verify the attraction names and pull additional info like addresses or websites. Enabling Google Search Grounding: In Vertex AI Studio, you simply toggle “Ground model responses” and choose Google Search as the source
cloud.google.com
. In code, you enable it by adding the Google Search tool in the request configuration. Make sure your project is allow-listed or has Google Search Suggestions enabled (as mentioned in prerequisites). Also note that Search grounding has a high daily quota (up to 1M queries/day)
cloud.google.com
 – more than enough for typical use, but it’s good to be aware if you plan to analyze videos at scale. Using the GenAI SDK with Search: The SDK provides a GoogleSearch tool you can attach. For instance:
from google.genai.types import GoogleSearch, Tool

response = client.models.generate_content(
    model="gemini-2.5-flash-preview-04-17",
    contents=[ video_part, prompt_text ],
    config=GenerateContentConfig(
        temperature=0.0,
        tools=[ Tool(google_search=GoogleSearch()) ]
    )
)
By adding Tool(google_search=GoogleSearch()) in the config, we allow Gemini to call out to Google Search when formulating its response
cloud.google.com
. The model might, for example, use search to confirm the spelling of a landmark or find a venue’s official details. Enriching Attraction Details: With grounding enabled, you can also ask for more detailed output. For example, extend the prompt: “…For each attraction, if possible include its address and official website.” Now the model can use web search results to fill in these fields. An example output could be:
[
  {
    "name": "Eiffel Tower",
    "type": "landmark",
    "address": "Champ de Mars, 5 Avenue Anatole France, 75007 Paris, France",
    "website": "https://www.toureiffel.paris/en"
  },
  {
    "name": "Café de Flore",
    "type": "restaurant",
    "address": "172 Boulevard Saint-Germain, 75006 Paris, France",
    "website": "http://cafedeflore.fr"
  }
]
Here the model likely recognized the Eiffel Tower from the video, then performed a search to get the exact address and official site. The “verified name” aspect comes naturally — because the model is pulling from real web data, the names tend to be accurate (e.g., “Café de Flore” instead of a misspelled variant). Grounded responses also include metadata called Search Suggestions – essentially the search query it used. If you inspect response.predictions[0].groundingMetadata.webSearchQueries, you’ll see queries like ["Eiffel Tower official website"]. If you build a user-facing app, you are required to display these suggestion queries to the user alongside the answer
cloud.google.com
cloud.google.com
, but if you’re just programmatically extracting data, you can use them for logging or debugging. Note: Grounded answers should still be treated carefully – while they’re more factual, the model might pick up incorrect data if the search results are misleading. Always consider verifying critical information via trusted APIs (e.g., Google Maps Places API for addresses) if absolute accuracy is needed. Grounding is extremely useful for augmenting the model’s knowledge with real-world data in real-time
cloud.google.com
.
Post-processing and Structuring Output
Once Gemini returns its analysis, we need to parse and post-process it into a final structured form. Assuming we requested JSON output, the first step is to parse the JSON string:
import json

result_text = response.text  # the model's raw output (string)
try:
    attractions = json.loads(result_text)
except json.JSONDecodeError:
    # If the model's output isn't perfect JSON, we might need to clean it up.
    # For example, remove trailing commas or fix quotes.
    cleaned = result_text.strip().strip("```")  # remove markdown formatting if any
    attractions = json.loads(cleaned)
Using json.loads will give us a Python list of dictionaries (each representing an attraction). If the model didn’t obey the format perfectly, some cleanup may be required. One strategy to enforce structure is to provide a few-shot example or a brief Pydantic schema in the prompt, but that often isn’t necessary for simpler outputs. If you prefer a Pydantic approach, you could define a model like:
from pydantic import BaseModel, ValidationError
from typing import List

class Attraction(BaseModel):
    name: str
    type: str
    address: str = None
    website: str = None

try:
    attractions = [Attraction(**item) for item in attractions]
except ValidationError as e:
    # handle any items that don't match schema
    print("Validation error:", e)
This will give you a list of Attraction objects, making it easy to work with the data in Python (with type hints and validation). Deduplication: It’s possible the model might mention the same attraction multiple times (for example, if it appears visually and in speech). It’s a good practice to deduplicate by name. You can do this by aggregating in a dict or using a set of names:
unique_attractions = {}
for attr in attractions:
    name = attr['name']
    if name not in unique_attractions:
        unique_attractions[name] = attr
# Now unique_attractions.values() contains unique entries
Alternatively, if slight variations of name occur (e.g. "Louvre" vs "Louvre Museum"), you may want to apply some normalization or string matching to decide if they are the same. In grounded mode, however, the model will likely use the official name from search results, reducing variance. Validation: If the context allows, cross-verify the attractions. For instance, if you expect only known places in a certain city, you could check the names against a list of known landmarks or use an external API to confirm existence. In our travel reel example, verifying that each name is a known POI (perhaps via a Maps API or a simple secondary search) could be a way to flag any hallucinations (unlikely with grounding, but worth ensuring if critical). Finally, you can structure the output as needed for downstream use. Perhaps you want a CSV of results or to store them in a database. Since you have them as Python objects/dicts now, that should be straightforward (e.g., using pandas or writing to Firestore, etc., depending on your application).
End-to-End Python Script Example
Below is an illustrative end-to-end script tying these pieces together. This script will: upload a video to GCS, call Gemini 2.5 Flash with search grounding to extract attractions, and print the structured results. (In a real application, you might integrate this in a cloud function or a web service.)
import os, json
from google.cloud import storage
from google import genai
from google.genai.types import Part, GenerateContentConfig, GoogleSearch, Tool

# Configure your project and auth (assumes env vars or ADC for credentials)
os.environ["GOOGLE_CLOUD_PROJECT"] = "<YOUR_PROJECT_ID>"
os.environ["GOOGLE_CLOUD_LOCATION"] = "global"
os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "True"

# 1. Upload video to Cloud Storage
bucket_name = "my-video-bucket"
video_file = "paris_day_out.mp4"
gcs_path = f"analysis_inputs/{video_file}"

storage_client = storage.Client()
bucket = storage_client.bucket(bucket_name)
blob = bucket.blob(gcs_path)
blob.upload_from_filename(video_file)
video_gcs_uri = f"gs://{bucket_name}/{gcs_path}"
print(f"Video uploaded to: {video_gcs_uri}")

# 2. Initialize GenAI (Vertex AI) client
client = genai.Client()  # uses env project and default credentials

# 3. Prepare prompt with video and text
video_part = Part.from_uri(file_uri=video_gcs_uri, mime_type="video/mp4")
prompt = (
    "You are an AI that extracts attractions from videos. "
    "Analyze the video and identify any attractions (landmarks, restaurants, or cultural sites) mentioned or shown. "
    "For each attraction, provide its name, type, address, and website in JSON format."
)

# 4. Call Gemini 2.5 Flash with Search grounding enabled
response = client.models.generate_content(
    model="gemini-2.5-flash-preview-04-17",
    contents=[ video_part, prompt ],
    config=GenerateContentConfig(
        temperature=0.0,
        tools=[ Tool(google_search=GoogleSearch()) ]
    )
)

# 5. Parse the response
output_text = response.text
try:
    data = json.loads(output_text)
except json.JSONDecodeError:
    # Basic cleanup if needed
    cleaned = output_text.strip().strip("```").strip()
    data = json.loads(cleaned)

# 6. Remove duplicate entries by name
unique = {}
for item in data:
    name = item.get("name")
    if name and name not in unique:
        unique[name] = item

attractions_list = list(unique.values())
print("Attractions found:")
for attr in attractions_list:
    print(f"- {attr.get('name')} ({attr.get('type')}): {attr.get('address')} - {attr.get('website')}")
Running something like the above will produce output in your console. For example, you might see:
Video uploaded to: gs://my-video-bucket/analysis_inputs/paris_day_out.mp4  
Attractions found:  
- Eiffel Tower (landmark): Champ de Mars, 5 Avenue Anatole France, 75007 Paris, France – https://www.toureiffel.paris/en  
- Louvre Museum (landmark): Rue de Rivoli, 75001 Paris, France – https://www.louvre.fr  
- Café de Flore (restaurant): 172 Boulevard Saint-Germain, 75006 Paris, France – http://cafedeflore.fr  
This indicates the model identified Eiffel Tower, Louvre Museum, and Café de Flore in the video and (with search help) provided their addresses and websites. Note: The actual output may vary based on the video content and how the prompt is worded. Adjust the prompt or parsing as necessary for your specific videos.
Best Practices and Limitations
Using Gemini 2.5 Flash for video analysis is cutting-edge, but there are some best practices and limitations to keep in mind:
Rate Limits & Quotas: Vertex AI’s generative models have quotas. Each video input counts toward your prompt token limits. There are also specific quotas for grounded requests (Google Search queries are capped at 1,000,000/day by default)
cloud.google.com
. If you plan to analyze many videos, monitor your quota usage in the Google Cloud console. Also, each request can include up to 10 videos and the total input size must be under the token limit (~1 million tokens, which is usually fine for short videos)
cloud.google.com
.
Latency: Analyzing video content is computationally intensive. Expect higher latency than a text-only prompt. A 60-second video may take several seconds for the model to process. Grounding with search can add a couple more seconds due to external queries. If latency is a concern, consider processing asynchronously (e.g., have Cloud Functions write results to a database that your app polls). Also note that very long videos (10+ minutes) might approach timeouts; chunking longer videos into segments could help.
Accuracy of Recognition: Gemini’s multimodal capabilities are state-of-the-art, but not infallible. It may miss an attraction if: (a) the video only briefly shows it or at an odd angle, (b) the name is spoken but not clearly, or (c) it’s an obscure place the model isn’t familiar with. To boost recall, ensure good quality inputs (clear audio, high-resolution video). You can also explicitly mention the context in the prompt (e.g., “This video is a travel vlog in Paris…” to prime the model). For critical applications, you might combine Gemini’s output with other signals (like GPS tags or manual hashtags from the video, if available).
Use of Transcripts vs Raw Video: As discussed, providing a transcript of the audio can improve recognition of spoken names and reduce the load on the model. If you have the transcript, you can even use a smaller model (text-only) to extract attractions from that. However, a transcript alone misses visual cues – someone might film the Taj Mahal without saying “Taj Mahal”. The ideal approach for precision is to combine modalities: you could prompt Gemini with both the transcript text and a few key frame images. For example, contents=[image1_part, image2_part, transcript_text, prompt_text]. In our case, Gemini 2.5 Flash can already handle combined video (visual+audio) internally, but this strategy is useful if you prefer preprocessing. It can also reduce cost, as processing a short transcript uses far fewer tokens than a full video.
Grounding Limitations: When using search grounding, the model’s answers are only as good as the search results. If an attraction has a common name, the search might return irrelevant info. You can mitigate this by providing more context in the query or prompt. For instance, include the city or video context in the prompt so the model’s search query is specific (“Cafe de Flore Paris address”). Always verify critical data from grounding – for example, if the model returns an address, double-check it if needed, since it might be quoting a Wikipedia article or some directory which could be outdated. Fortunately, Google Search is generally reliable for well-known places.
Costs: Vertex AI generative models (especially multimodal ones) have usage costs based on input and output tokens. Video and image inputs are converted into tokens via vision encoding. Short videos won’t break the bank, but if you plan to analyze thousands of videos, keep an eye on your billing. Using the Flash model is cheaper than the Pro model for a slight quality trade-off, which is why we target Flash for a high-volume use case
ai.google.dev
. Where appropriate, do preprocessing (like transcripts) to reduce token usage.
Model Behavior and System Instructions: Gemini models allow system instructions to guide behavior (like a system message in a chat). In our prompt, we implicitly instructed the behavior. For more complex logic (e.g., “only output unique names” or “if unsure, say ‘Unknown’”), you can add a system role message. The GenAI SDK supports chat-style prompts with roles. This can help enforce format or rules.
Future Improvements: Google’s AI offerings evolve rapidly. Keep an eye on Vertex AI announcements – newer versions of Gemini might improve accuracy or add native features (like directly outputting structured data or a built-in place name recognizer). Also, Google could introduce domain-specific models or tools (for example, a “places recognizer” or integration with Google Maps data) that might complement this task. As of now, Gemini 2.5 Flash with search grounding is a cutting-edge solution to parse video content for points of interest.
By following this guide, you should be able to build a robust pipeline on Google Cloud that takes in short videos and outputs the attractions featured in them, complete with real-world details. You’ve combined the power of a multimodal AI model with web grounding to bridge the gap between unstructured video content and structured, actionable data. Good luck, and happy building! Sources: Official Google Cloud documentation and blogs were referenced throughout this guide for accuracy, including details on Gemini 2.5 Flash capabilities
ai.google.dev
, video input support
cloud.google.com
, and search grounding usage
cloud.google.com
, among others.