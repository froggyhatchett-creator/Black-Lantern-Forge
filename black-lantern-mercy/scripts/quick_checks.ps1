# Manual spot checks, no Python needed. Run line by line, or the whole file.
$E = "http://127.0.0.1:11434"
"--- version / installed models (Mercy's discovery call is /api/tags) ---"
(Invoke-RestMethod "$E/api/version").version
(Invoke-RestMethod "$E/api/tags").models | Select-Object name, @{n="GB";e={[math]::Round($_.size/1GB,1)}}

"--- thinking OFF vs ON, qwen3.5:4b; look at total_duration, eval_count, and whether message.thinking is non-empty ---"
foreach ($think in @($false, $true)) {
  $body = @{ model="qwen3.5:4b"; stream=$false; think=$think; options=@{num_predict=600}
             messages=@(@{role="user"; content="In one sentence, what is a mutex?"}) } | ConvertTo-Json -Depth 6
  $r = Invoke-RestMethod "$E/api/chat" -Method Post -Body $body -ContentType "application/json" -TimeoutSec 300
  "think={0}: total {1:N1}s, load {2:N1}s, eval_count {3}, tok/s {4:N1}, thinking_chars {5}, answer: {6}" -f $think,
    ($r.total_duration/1e9), ($r.load_duration/1e9), $r.eval_count, ($r.eval_count/($r.eval_duration/1e9)),
    ($r.message.thinking).Length, $r.message.content
}

"--- what window is actually loaded? CONTEXT column = effective num_ctx ---"
ollama ps
