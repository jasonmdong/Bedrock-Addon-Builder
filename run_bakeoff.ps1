# run_bakeoff.ps1
# RCAC Model Bake-Off: Compare 3 models via Scholar V100 GPU (reasoning strategy)

# Define the models to test
$models = @("qwen2.5-coder:7b", "deepseek-coder-v2", "yi-coder:9b")

# Strategy for this run
$strategy = "zero_shot"

# Define the Tunnel URL (Pointing to Scholar via SSH tunnel)
$tunnelUrl = "http://localhost:11435"

# Create logs directory if it doesn't exist
New-Item -ItemType Directory -Force -Path "logs" | Out-Null

Write-Host "Starting RCAC Model Bake-Off..." -ForegroundColor Yellow
Write-Host "Targeting Remote GPU via: $tunnelUrl" -ForegroundColor Gray
Write-Host "Strategy: $strategy" -ForegroundColor Gray
Write-Host "-----------------------------------"

foreach ($model in $models) {
    Write-Host "Testing Model: $model" -ForegroundColor Cyan

    # Sanitize model name for filename (replace : with -)
    $safeName = $model -replace ":", "-"

    # Run the evaluation
    python scripts/evaluate_llm.py `
        --provider ollama `
        --model $model `
        --strategy $strategy `
        --ollama-url $tunnelUrl `
        --all `
        | Tee-Object -FilePath "logs\bakeoff_${safeName}_${strategy}.txt"

    Write-Host "Finished $model" -ForegroundColor Green
    Write-Host "-----------------------------------"
}

Write-Host "Bake-Off Complete. Results saved in 'logs/' folder." -ForegroundColor Yellow
Write-Host ""
Write-Host "Quick comparison:" -ForegroundColor Cyan
Select-String "Score:" logs\bakeoff_*.txt
