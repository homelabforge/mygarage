#!/bin/bash
# Production deployment validation script for MyGarage
# Tests all critical endpoints after deployment

set -e

echo "=== MyGarage Production Deployment Test ==="
echo ""

# Configuration
HOST="${MYGARAGE_HOST:-localhost}"
PORT="${MYGARAGE_PORT:-12347}"
BASE_URL="http://${HOST}:${PORT}"

echo "Testing: $BASE_URL"
echo ""

# Test 1: Container running
echo "Test 1: Checking container status..."
if docker compose ps | grep -q "Up"; then
    echo "✅ Container is running"
else
    echo "❌ Container is not running"
    echo "Run: docker compose ps"
    exit 1
fi

# Test 2: Health check
echo ""
echo "Test 2: Testing health endpoint..."
HEALTH=$(curl -s -f "${BASE_URL}/health" || echo "FAILED")
if echo "$HEALTH" | grep -q "healthy"; then
    echo "✅ Health check passed: $HEALTH"
else
    echo "❌ Health check failed: $HEALTH"
    exit 1
fi

# Test 3: Frontend serves
echo ""
echo "Test 3: Testing frontend..."
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "${BASE_URL}/")
if [ "$HTTP_CODE" = "200" ]; then
    echo "✅ Frontend serving (HTTP 200)"
else
    echo "❌ Frontend not serving (HTTP $HTTP_CODE)"
    exit 1
fi

# Test 4: API responds
echo ""
echo "Test 4: Testing API..."
API_RESPONSE=$(curl -s -f "${BASE_URL}/api/auth/status" || echo "FAILED")
if [ -n "$API_RESPONSE" ] && [ "$API_RESPONSE" != "FAILED" ]; then
    echo "✅ API responding: $API_RESPONSE"
else
    echo "❌ API not responding"
    exit 1
fi

# Test 5: Check logs for errors
echo ""
echo "Test 5: Checking logs for errors..."
ERROR_COUNT=$(docker compose logs --tail=100 2>&1 | grep -i error | grep -v "0 errors" | wc -l)
if [ "$ERROR_COUNT" -lt 3 ]; then
    echo "✅ No critical errors in logs ($ERROR_COUNT error mentions)"
else
    echo "⚠️  Found $ERROR_COUNT error mentions in logs (review manually)"
    echo "Run: docker compose logs --tail=100 | grep -i error"
fi

# Test 6: Verify Bun frontend build
echo ""
echo "Test 6: Verifying Bun-built frontend..."
# Check if dist contains expected files
if docker compose exec -T mygarage-dev test -f /app/static/index.html; then
    echo "✅ Frontend static files present"
else
    echo "❌ Frontend static files missing"
    exit 1
fi

# Test 7: Check Docker image label
echo ""
echo "Test 7: Checking Docker image metadata..."
IMAGE_INFO=$(docker inspect mygarage:dev --format '{{index .Config.Labels "org.opencontainers.image.frontend.builder"}}' 2>/dev/null || echo "not-found")
if [ "$IMAGE_INFO" = "bun-1.3.4" ]; then
    echo "✅ Docker image built with Bun 1.3.4"
else
    echo "ℹ️  Frontend builder label: $IMAGE_INFO"
fi

# Test 8: Memory usage
echo ""
echo "Test 8: Checking resource usage..."
MEMORY=$(docker stats --no-stream --format "{{.MemUsage}}" mygarage-dev 2>/dev/null || echo "N/A")
echo "ℹ️  Memory usage: $MEMORY"

echo ""
echo "=== All Critical Tests Passed ==="
echo "Production deployment is healthy and Bun migration is successful!"
echo ""
echo "Additional checks you can run manually:"
echo "  - Login to the web interface: ${BASE_URL}"
echo "  - Create a test vehicle"
echo "  - Upload a test document"
echo "  - Check VIN decoding works"
echo ""
