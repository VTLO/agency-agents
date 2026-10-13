package fr.j3anclaud3.compagnon

import com.anthropic.client.AnthropicClient
import com.anthropic.client.okhttp.AnthropicOkHttpClient
import com.anthropic.errors.PermissionDeniedException
import com.anthropic.errors.UnauthorizedException
import com.anthropic.models.messages.MessageCreateParams
import com.anthropic.models.messages.OutputConfig
import com.anthropic.models.messages.StopReason
import java.time.Duration

/** Claude through the official Anthropic Java SDK ("claude" flavor only). */
class ClaudeModel(apiKey: String, override val model: String, baseUrl: String = Prefs.DEFAULT_API_URL) : ChatModel {
    override val provider = Provider.CLAUDE

    private val client: AnthropicClient = AnthropicOkHttpClient.builder()
        .apiKey(apiKey)
        .baseUrl(baseUrl)
        .maxRetries(2)
        .timeout(Duration.ofSeconds(60))
        .build()

    override fun complete(system: String, history: List<Line>, user: String, maxTokens: Int): Completion {
        val params = MessageCreateParams.builder()
            .model(model)
            .maxTokens(maxTokens.toLong())
            .system(system)
        history.forEach { if (it.me) params.addUserMessage(it.text) else params.addAssistantMessage(it.text) }
        params.addUserMessage(user)
        // Haiku takes no effort setting; Sonnet/Opus answer short chat turns well at low effort.
        if (!model.contains("haiku")) params.outputConfig(OutputConfig.builder().effort(OutputConfig.Effort.LOW).build())

        val response = try {
            client.messages().create(params.build())
        } catch (e: UnauthorizedException) {
            throw AuthRejected("Clé API Anthropic refusée")
        } catch (e: PermissionDeniedException) {
            throw AuthRejected("Clé API Anthropic sans accès")
        }
        val usage = response.usage()
        val input = usage.inputTokens() + usage.cacheReadInputTokens().orElse(0L)
        if (response.stopReason().orElse(null) == StopReason.REFUSAL) return Completion("", input, usage.outputTokens())
        val text = response.content().mapNotNull { block -> block.text().map { it.text() }.orElse(null) }.joinToString("")
        return Completion(text, input, usage.outputTokens())
    }
}
