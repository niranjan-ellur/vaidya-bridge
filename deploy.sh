#!/bin/bash
# VaidyaBridge Cloud Run Deploy Script
# Usage: ./deploy.sh YOUR_PROJECT_ID YOUR_GEMINI_KEY YOUR_MAPS_KEY

PROJECT_ID=${1:-"YOUR_GCP_PROJECT_ID"}
GEMINI_KEY=${2:-"YOUR_GEMINI_API_KEY"}
MAPS_KEY=${3:-"YOUR_MAPS_API_KEY"}
REGION="asia-south1"
SERVICE="vaidya-bridge"
IMAGE="gcr.io/$PROJECT_ID/$SERVICE"

echo "🚀 Building and deploying VaidyaBridge to Cloud Run..."
echo "Project: $PROJECT_ID | Region: $REGION"

gcloud config set project $PROJECT_ID

echo "📦 Building container..."
gcloud builds submit --tag $IMAGE

echo "🌐 Deploying to Cloud Run..."
gcloud run deploy $SERVICE \
  --image $IMAGE \
  --platform managed \
  --region $REGION \
  --allow-unauthenticated \
  --memory 512Mi \
  --cpu 1 \
  --timeout 120 \
  --set-env-vars "GEMINI_API_KEY=$GEMINI_KEY,GOOGLE_MAPS_API_KEY=$MAPS_KEY"

echo "✅ Deployed! Check URL above."
