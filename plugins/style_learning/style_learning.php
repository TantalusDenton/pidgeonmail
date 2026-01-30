<?php

/**
 * Style Learning Plugin.
 *
 * Plugin that captures user-written email replies and sends them to a Python
 * LangGraph service for style analysis, building a personalized writing profile.
 *
 * @license GNU GPLv3+
 * @author Style Learning Plugin
 *
 * @website https://roundcube.net
 */
class style_learning extends rcube_plugin
{
    public $task = 'mail';

    /** @var rcmail */
    private $rc;

    /**
     * Plugin initialization.
     */
    #[\Override]
    public function init()
    {
        $this->rc = rcmail::get_instance();

        // Hook into message_sent to capture user-written messages
        $this->add_hook('message_sent', [$this, 'on_message_sent']);
    }

    /**
     * Handler for 'message_sent' hook - triggered after a message is sent.
     *
     * @param array $args Hook arguments containing headers, body, etc.
     *
     * @return array Arguments (unchanged)
     */
    public function on_message_sent($args)
    {
        $this->load_config();

        // Check if plugin is enabled
        if (!$this->rc->config->get('style_learning_enabled', true)) {
            return $args;
        }

        // Skip AI-generated messages
        if ($this->is_ai_generated($args)) {
            rcube::write_log('style_learning', 'Skipping AI-generated message');
            return $args;
        }

        // Extract message body
        $message_body = $this->extract_message_body($args);
        if (empty($message_body)) {
            return $args;
        }

        // Check minimum length
        $min_length = $this->rc->config->get('style_learning_min_length', 50);
        if (strlen($message_body) < $min_length) {
            rcube::write_log('style_learning', 'Message too short for style learning');
            return $args;
        }

        // Get message context
        $context = $this->extract_context($args);

        // Send to style learning service (async)
        $this->send_to_style_service($message_body, $context);

        return $args;
    }

    /**
     * Check if message was AI-generated.
     *
     * @param array $args Message arguments
     *
     * @return bool True if AI-generated
     */
    private function is_ai_generated($args)
    {
        // Check for X-AI-Generated header
        $headers = $args['headers'] ?? [];

        if (is_array($headers)) {
            foreach ($headers as $key => $value) {
                if (strtolower($key) === 'x-ai-generated') {
                    return true;
                }
            }
        }

        // Also check the message object if available
        if (isset($args['message']) && $args['message'] instanceof rcube_message) {
            $ai_header = $args['message']->headers->get('x-ai-generated');
            if ($ai_header) {
                return true;
            }
        }

        return false;
    }

    /**
     * Extract message body from sent message arguments.
     *
     * @param array $args Message arguments
     *
     * @return string Message body text
     */
    private function extract_message_body($args)
    {
        $body = '';

        // Try to get body from args
        if (!empty($args['body'])) {
            $body = $args['body'];
        } elseif (!empty($args['message'])) {
            // Handle Mail_mime object
            if ($args['message'] instanceof Mail_mime) {
                $body = $args['message']->getTXTBody();
                if (empty($body)) {
                    $html = $args['message']->getHTMLBody();
                    if (!empty($html)) {
                        $body = rcube_html2text::convert($html);
                    }
                }
            }
        }

        // Clean up the body
        if (!empty($body)) {
            // Remove quoted text (lines starting with >)
            $lines = explode("\n", $body);
            $clean_lines = [];
            foreach ($lines as $line) {
                // Skip quoted lines
                if (preg_match('/^>/', ltrim($line))) {
                    continue;
                }
                // Skip attribution lines like "On X date, Y wrote:"
                if (preg_match('/^On .+ wrote:$/i', trim($line))) {
                    continue;
                }
                $clean_lines[] = $line;
            }
            $body = implode("\n", $clean_lines);
        }

        return trim($body);
    }

    /**
     * Extract context information about the message.
     *
     * @param array $args Message arguments
     *
     * @return array Context data
     */
    private function extract_context($args)
    {
        $context = [
            'is_reply' => false,
            'original_subject' => null,
        ];

        // Check for In-Reply-To or References header
        $headers = $args['headers'] ?? [];
        if (is_array($headers)) {
            foreach ($headers as $key => $value) {
                $key_lower = strtolower($key);
                if ($key_lower === 'in-reply-to' || $key_lower === 'references') {
                    $context['is_reply'] = true;
                    break;
                }
            }
        }

        // Get subject
        if (!empty($args['headers']['Subject'])) {
            $subject = $args['headers']['Subject'];
            // Check if it's a reply based on subject prefix
            if (preg_match('/^(Re|RE|Fwd|FW):/i', $subject)) {
                $context['is_reply'] = true;
                $context['original_subject'] = preg_replace('/^(Re|RE|Fwd|FW):\s*/i', '', $subject);
            }
        }

        return $context;
    }

    /**
     * Send message to style learning service.
     *
     * @param string $message_body Message body text
     * @param array  $context      Message context
     */
    private function send_to_style_service($message_body, $context)
    {
        $service_url = $this->rc->config->get('style_learning_service_url', 'http://localhost:8000');
        $api_key = $this->rc->config->get('style_learning_api_key', '');

        // Get user identifier (use email or ID)
        $identities = $this->rc->user->list_identities();
        $user_id = !empty($identities[0]['email']) ? $identities[0]['email'] : 'user_' . $this->rc->user->ID;

        // Build request payload
        $payload = [
            'user_id' => $user_id,
            'message' => [
                'body' => $message_body,
                'subject' => $context['original_subject'] ?? '',
                'recipients' => [],
                'timestamp' => gmdate('Y-m-d\TH:i:s\Z'),
            ],
            'context' => [
                'is_reply' => $context['is_reply'],
                'original_subject' => $context['original_subject'],
            ],
        ];

        // Make HTTP request to style learning service
        $url = rtrim($service_url, '/') . '/api/v1/learn';

        $ch = curl_init($url);
        curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
        curl_setopt($ch, CURLOPT_POST, true);
        curl_setopt($ch, CURLOPT_POSTFIELDS, json_encode($payload));
        curl_setopt($ch, CURLOPT_TIMEOUT, 5); // Short timeout for non-blocking feel
        curl_setopt($ch, CURLOPT_CONNECTTIMEOUT, 2);

        $headers = ['Content-Type: application/json'];
        if (!empty($api_key)) {
            $headers[] = 'X-API-Key: ' . $api_key;
        }
        curl_setopt($ch, CURLOPT_HTTPHEADER, $headers);

        $response = curl_exec($ch);
        $http_code = curl_getinfo($ch, CURLINFO_HTTP_CODE);
        $error = curl_error($ch);
        curl_close($ch);

        if ($error) {
            rcube::write_log('style_learning', "cURL error: {$error}");
            return;
        }

        if ($http_code !== 200) {
            rcube::write_log('style_learning', "Style service error: HTTP {$http_code} - {$response}");
            return;
        }

        $result = json_decode($response, true);
        if (!empty($result['success'])) {
            rcube::write_log('style_learning', "Style learning successful. Samples: {$result['samples_count']}");
        } else {
            rcube::write_log('style_learning', "Style learning failed: " . ($result['message'] ?? 'Unknown error'));
        }
    }

    /**
     * Get user's style profile from the service.
     *
     * @param string|null $user_id Optional user ID (defaults to current user)
     *
     * @return array|null Style profile or null on failure
     */
    public function get_user_style($user_id = null)
    {
        $this->load_config();

        $service_url = $this->rc->config->get('style_learning_service_url', 'http://localhost:8000');
        $api_key = $this->rc->config->get('style_learning_api_key', '');

        if ($user_id === null) {
            $identities = $this->rc->user->list_identities();
            $user_id = !empty($identities[0]['email']) ? $identities[0]['email'] : 'user_' . $this->rc->user->ID;
        }

        $url = rtrim($service_url, '/') . '/api/v1/style/' . urlencode($user_id);

        $ch = curl_init($url);
        curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
        curl_setopt($ch, CURLOPT_TIMEOUT, 5);

        $headers = ['Content-Type: application/json'];
        if (!empty($api_key)) {
            $headers[] = 'X-API-Key: ' . $api_key;
        }
        curl_setopt($ch, CURLOPT_HTTPHEADER, $headers);

        $response = curl_exec($ch);
        $http_code = curl_getinfo($ch, CURLINFO_HTTP_CODE);
        $error = curl_error($ch);
        curl_close($ch);

        if ($error) {
            rcube::write_log('style_learning', "cURL error fetching style: {$error}");
            return null;
        }

        if ($http_code === 404) {
            // No profile yet, not an error
            return null;
        }

        if ($http_code !== 200) {
            rcube::write_log('style_learning', "Style service error: HTTP {$http_code}");
            return null;
        }

        return json_decode($response, true);
    }
}
