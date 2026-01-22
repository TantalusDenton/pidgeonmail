<?php

/**
 * AI Auto-Reply Plugin.
 *
 * Plugin that automatically generates AI-powered draft replies to received emails
 * using OpenAI API, with optional auto-send capability.
 *
 * @license GNU GPLv3+
 * @author AI Auto-Reply Plugin
 *
 * @website https://roundcube.net
 */
class ai_autoreply extends rcube_plugin
{
    public $task = 'mail|settings';

    /** @var rcmail */
    private $rc;

    /** @var array Rate limiting cache */
    private static $rate_limit_cache = [];

    /**
     * Plugin initialization.
     */
    #[\Override]
    public function init()
    {
        $this->rc = rcmail::get_instance();

        $this->add_hook('message_read', [$this, 'on_message_read']);

        if ($this->rc->task == 'settings') {
            $this->add_hook('preferences_list', [$this, 'preferences_list']);
            $this->add_hook('preferences_save', [$this, 'preferences_save']);
        }
    }

    /**
     * Handler for 'message_read' hook - triggered when a message is viewed.
     *
     * @param array $args Hook arguments containing uid, mailbox, and message
     *
     * @return array Modified arguments
     */
    public function on_message_read($args)
    {
        $this->load_config();

        // Check if plugin is enabled
        if (!$this->rc->config->get('ai_autoreply_enabled', false)) {
            return $args;
        }

        // Get API key
        $api_key = $this->rc->config->get('ai_autoreply_openai_key', '');
        if (empty($api_key)) {
            return $args;
        }

        $message = $args['message'] ?? null;
        if (!$message || !($message instanceof rcube_message)) {
            return $args;
        }

        // Check if message should be skipped
        if ($this->should_skip_message($message)) {
            return $args;
        }

        // Generate AI reply
        $reply_text = $this->generate_ai_reply($message, $api_key);
        if (empty($reply_text)) {
            return $args;
        }

        // Check auto-send setting
        $auto_send = $this->rc->config->get('ai_autoreply_autosend', false);

        if ($auto_send && $this->can_auto_send($message)) {
            $this->auto_send_reply($message, $reply_text);
        } else {
            $this->save_draft($message, $reply_text);
        }

        return $args;
    }

    /**
     * Determine if a message should be skipped for AI reply.
     *
     * @param rcube_message $message The email message
     *
     * @return bool True if message should be skipped
     */
    private function should_skip_message($message)
    {
        // Skip if no headers
        if (empty($message->headers)) {
            return true;
        }

        // Skip messages from self (check against all identities)
        $identities = $this->rc->user->list_identities();
        $from = $message->sender['mailto'] ?? '';
        $from_lower = strtolower($from);

        foreach ($identities as $identity) {
            if (strtolower($identity['email']) === $from_lower) {
                return true; // Message from self
            }
        }

        // Skip drafts folder
        $drafts_mbox = $this->rc->config->get('drafts_mbox', 'Drafts');
        if ($message->folder === $drafts_mbox) {
            return true;
        }

        // Skip sent folder
        $sent_mbox = $this->rc->config->get('sent_mbox', 'Sent');
        if ($message->folder === $sent_mbox) {
            return true;
        }

        // Skip auto-generated messages
        $auto_submitted = $message->headers->others['auto-submitted'] ?? null;
        if ($auto_submitted && strtolower($auto_submitted) !== 'no') {
            return true;
        }

        // Skip mailing list messages
        if ($message->headers->others['list-unsubscribe'] ?? null) {
            return true;
        }
        if ($message->headers->others['list-id'] ?? null) {
            return true;
        }
        if ($message->headers->get('list-post', false)) {
            return true;
        }

        // Skip messages with Precedence: bulk or list
        $precedence = $message->headers->others['precedence'] ?? null;
        if ($precedence && in_array(strtolower($precedence), ['bulk', 'list', 'junk'])) {
            return true;
        }

        return false;
    }

    /**
     * Check if auto-send is allowed based on safeguards.
     *
     * @param rcube_message $message The original message
     *
     * @return bool True if auto-send is allowed
     */
    private function can_auto_send($message)
    {
        // Safeguard 1: Rate limit - max 10 auto-sends per hour
        $user_id = $this->rc->user->ID;
        $cache_key = "ai_autoreply_rate_{$user_id}";
        $rate_data = $_SESSION[$cache_key] ?? ['count' => 0, 'reset_time' => time() + 3600];

        if (time() > $rate_data['reset_time']) {
            $rate_data = ['count' => 0, 'reset_time' => time() + 3600];
        }

        if ($rate_data['count'] >= 10) {
            rcube::write_log('ai_autoreply', 'Auto-send rate limit reached');
            return false;
        }

        // Safeguard 2: Skip messages older than 1 hour
        $message_date = $message->headers->date ?? null;
        if ($message_date) {
            $msg_time = strtotime($message_date);
            if ($msg_time && (time() - $msg_time) > 3600) {
                return false;
            }
        }

        // Safeguard 3: Skip group emails (more than 3 recipients)
        $to_count = 0;
        $cc_count = 0;

        if (!empty($message->headers->to)) {
            $to_addresses = rcube_mime::decode_address_list($message->headers->to);
            $to_count = count($to_addresses);
        }
        if (!empty($message->headers->cc)) {
            $cc_addresses = rcube_mime::decode_address_list($message->headers->cc);
            $cc_count = count($cc_addresses);
        }

        if (($to_count + $cc_count) > 3) {
            return false;
        }

        // Safeguard 4: Check for duplicate reply in same thread
        $message_id = $message->headers->get('message-id');
        $replied_key = "ai_autoreply_replied_{$user_id}";
        $replied_messages = $_SESSION[$replied_key] ?? [];

        if (in_array($message_id, $replied_messages)) {
            return false;
        }

        return true;
    }

    /**
     * Generate AI reply using OpenAI API.
     *
     * @param rcube_message $message The original email message
     * @param string        $api_key OpenAI API key
     *
     * @return string|null Generated reply text or null on failure
     */
    private function generate_ai_reply($message, $api_key)
    {
        // Extract message text
        $message_text = $this->extract_message_text($message);
        if (empty($message_text)) {
            return null;
        }

        // Build prompt
        $sender_name = $message->sender['name'] ?? $message->sender['mailto'] ?? 'the sender';
        $subject = $message->subject ?? '(no subject)';

        $prompt = "You are a helpful email assistant. Write a professional and friendly reply to the following email.\n\n";
        $prompt .= "From: {$sender_name}\n";
        $prompt .= "Subject: {$subject}\n\n";
        $prompt .= "Email content:\n{$message_text}\n\n";
        $prompt .= "Write a concise, professional reply. Do not include subject line or email headers in your response, just the body text.";

        // Call OpenAI API
        $model = $this->rc->config->get('ai_autoreply_model', 'gpt-4o-mini');
        $reply = $this->call_openai_api($prompt, $api_key, $model);

        return $reply;
    }

    /**
     * Extract plain text content from message.
     *
     * @param rcube_message $message The email message
     *
     * @return string Message text content
     */
    private function extract_message_text($message)
    {
        $text = '';

        // Try to get plain text part first
        if (!empty($message->parts)) {
            foreach ($message->parts as $part) {
                if ($part->type === 'content' && $part->ctype_secondary === 'plain') {
                    $body = $message->get_part_body($part->mime_id, true);
                    if ($body !== false) {
                        $text = $body;
                        break;
                    }
                }
            }

            // Fall back to HTML if no plain text
            if (empty($text)) {
                foreach ($message->parts as $part) {
                    if ($part->type === 'content' && $part->ctype_secondary === 'html') {
                        $body = $message->get_part_body($part->mime_id, true);
                        if ($body !== false) {
                            // Convert HTML to plain text
                            $text = rcube_html2text::convert($body);
                            break;
                        }
                    }
                }
            }
        }

        // Fall back to body property
        if (empty($text) && !empty($message->body)) {
            $text = $message->body;
        }

        // Truncate if too long (keep it reasonable for API)
        $max_length = 4000;
        if (strlen($text) > $max_length) {
            $text = substr($text, 0, $max_length) . "\n\n[Message truncated...]";
        }

        return trim($text);
    }

    /**
     * Call OpenAI API to generate reply.
     *
     * @param string $prompt  The prompt to send
     * @param string $api_key OpenAI API key
     * @param string $model   Model name
     *
     * @return string|null Generated text or null on failure
     */
    private function call_openai_api($prompt, $api_key, $model = 'gpt-4o-mini')
    {
        $url = 'https://api.openai.com/v1/chat/completions';

        $data = [
            'model' => $model,
            'messages' => [
                ['role' => 'user', 'content' => $prompt],
            ],
            'max_tokens' => 1000,
            'temperature' => 0.7,
        ];

        $ch = curl_init($url);
        curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
        curl_setopt($ch, CURLOPT_POST, true);
        curl_setopt($ch, CURLOPT_POSTFIELDS, json_encode($data));
        curl_setopt($ch, CURLOPT_HTTPHEADER, [
            'Content-Type: application/json',
            'Authorization: Bearer ' . $api_key,
        ]);
        curl_setopt($ch, CURLOPT_TIMEOUT, 30);

        $response = curl_exec($ch);
        $http_code = curl_getinfo($ch, CURLINFO_HTTP_CODE);
        $error = curl_error($ch);
        curl_close($ch);

        if ($error) {
            rcube::write_log('ai_autoreply', "cURL error: {$error}");
            return null;
        }

        if ($http_code !== 200) {
            rcube::write_log('ai_autoreply', "OpenAI API error: HTTP {$http_code} - {$response}");
            return null;
        }

        $result = json_decode($response, true);
        if (empty($result['choices'][0]['message']['content'])) {
            rcube::write_log('ai_autoreply', 'OpenAI API: Empty response');
            return null;
        }

        return trim($result['choices'][0]['message']['content']);
    }

    /**
     * Save the generated reply as a draft.
     *
     * @param rcube_message $original   Original message
     * @param string        $reply_text Generated reply text
     *
     * @return bool True on success
     */
    private function save_draft($original, $reply_text)
    {
        $storage = $this->rc->get_storage();
        $drafts_mbox = $this->rc->config->get('drafts_mbox', 'Drafts');

        // Ensure drafts folder exists
        if (!$storage->folder_exists($drafts_mbox, true)) {
            if (!$storage->folder_exists($drafts_mbox)) {
                $storage->create_folder($drafts_mbox, true);
            } else {
                $storage->subscribe($drafts_mbox);
            }
        }

        // Get identity for From header
        $identities = $this->rc->user->list_identities();
        $identity = !empty($identities) ? $identities[0] : null;

        // Determine reply-to address
        $reply_to = '';
        if (!empty($original->headers->replyto)) {
            $reply_to = $original->headers->replyto;
        } elseif (!empty($original->sender['mailto'])) {
            $reply_to = $original->sender['mailto'];
        } elseif (!empty($original->headers->from)) {
            $reply_to = $original->headers->from;
        }

        // Build reply subject
        $subject = rcmail_sendmail::reply_subject($original->subject);

        // Build references
        $references = '';
        $in_reply_to = '';
        $message_id = $original->headers->get('message-id');
        if ($message_id) {
            $in_reply_to = $message_id;
            $orig_refs = $original->headers->get('references');
            $references = trim(($orig_refs ? $orig_refs . ' ' : '') . $message_id);
        }

        // Build draft info header
        $draft_info = rcmail_sendmail::draftinfo_encode([
            'type' => 'reply',
            'uid' => $original->uid,
            'folder' => $original->folder,
        ]);

        // Compose message
        $from = $identity ? format_email_recipient($identity['email'], $identity['name']) : '';
        $date = date('r');
        $boundary = '----=_Part_' . md5(microtime());

        // Generate Message-ID
        $msg_id = $this->rc->gen_message_id($identity ? $identity['email'] : '');

        // Build headers
        $headers = "Date: {$date}\r\n";
        $headers .= "From: {$from}\r\n";
        $headers .= "To: {$reply_to}\r\n";
        $headers .= "Subject: " . rcube_mime::encode_header_value('Subject', $subject, RCUBE_CHARSET) . "\r\n";
        $headers .= "Message-ID: {$msg_id}\r\n";
        if ($in_reply_to) {
            $headers .= "In-Reply-To: {$in_reply_to}\r\n";
        }
        if ($references) {
            $headers .= "References: {$references}\r\n";
        }
        $headers .= "X-Draft-Info: {$draft_info}\r\n";
        $headers .= "X-AI-Generated: true\r\n";
        $headers .= "MIME-Version: 1.0\r\n";
        $headers .= "Content-Type: text/plain; charset=UTF-8\r\n";
        $headers .= "Content-Transfer-Encoding: 8bit\r\n";

        // Build message
        $message = $headers . "\r\n" . $reply_text;

        // Save to drafts
        $saved = $storage->save_message($drafts_mbox, $message);

        if ($saved) {
            rcube::write_log('ai_autoreply', "Draft saved for message UID {$original->uid}");
        } else {
            rcube::write_log('ai_autoreply', "Failed to save draft for message UID {$original->uid}");
        }

        return (bool) $saved;
    }

    /**
     * Auto-send the generated reply with safeguards.
     *
     * @param rcube_message $original   Original message
     * @param string        $reply_text Generated reply text
     *
     * @return bool True on success
     */
    private function auto_send_reply($original, $reply_text)
    {
        // Get identity
        $identities = $this->rc->user->list_identities();
        $identity = !empty($identities) ? $identities[0] : null;

        if (!$identity) {
            rcube::write_log('ai_autoreply', 'No identity found for auto-send');
            return false;
        }

        // Determine reply-to address
        $reply_to = '';
        if (!empty($original->headers->replyto)) {
            $addresses = rcube_mime::decode_address_list($original->headers->replyto);
            $reply_to = !empty($addresses) ? array_first($addresses)['mailto'] : '';
        } elseif (!empty($original->sender['mailto'])) {
            $reply_to = $original->sender['mailto'];
        }

        if (empty($reply_to)) {
            rcube::write_log('ai_autoreply', 'No reply-to address found');
            return false;
        }

        // Build subject
        $subject = rcmail_sendmail::reply_subject($original->subject);

        // Build references
        $references = '';
        $in_reply_to = '';
        $message_id = $original->headers->get('message-id');
        if ($message_id) {
            $in_reply_to = $message_id;
            $orig_refs = $original->headers->get('references');
            $references = trim(($orig_refs ? $orig_refs . ' ' : '') . $message_id);
        }

        // Create MIME message
        $MAIL_MIME = new Mail_mime("\r\n");
        $MAIL_MIME->setTXTBody($reply_text);

        $from_string = format_email_recipient($identity['email'], $identity['name']);
        $msg_id = $this->rc->gen_message_id($identity['email']);

        $headers = [
            'Date' => date('r'),
            'From' => $from_string,
            'To' => $reply_to,
            'Subject' => $subject,
            'Message-ID' => $msg_id,
            'X-AI-Generated' => 'true',
        ];

        if ($in_reply_to) {
            $headers['In-Reply-To'] = $in_reply_to;
        }
        if ($references) {
            $headers['References'] = $references;
        }

        $MAIL_MIME->headers($headers);

        // Set encoding
        $MAIL_MIME->setParam('text_encoding', '8bit');
        $MAIL_MIME->setParam('head_encoding', 'quoted-printable');
        $MAIL_MIME->setParam('head_charset', RCUBE_CHARSET);
        $MAIL_MIME->setParam('text_charset', RCUBE_CHARSET);

        // Send message
        $smtp_error = null;
        $mailbody_file = null;
        $sent = $this->rc->deliver_message($MAIL_MIME, $identity['email'], $reply_to, $smtp_error, $mailbody_file);

        if ($sent) {
            // Update rate limit
            $user_id = $this->rc->user->ID;
            $cache_key = "ai_autoreply_rate_{$user_id}";
            $rate_data = $_SESSION[$cache_key] ?? ['count' => 0, 'reset_time' => time() + 3600];
            $rate_data['count']++;
            $_SESSION[$cache_key] = $rate_data;

            // Track replied messages
            $replied_key = "ai_autoreply_replied_{$user_id}";
            $replied_messages = $_SESSION[$replied_key] ?? [];
            $replied_messages[] = $message_id;
            // Keep only last 100 message IDs
            if (count($replied_messages) > 100) {
                $replied_messages = array_slice($replied_messages, -100);
            }
            $_SESSION[$replied_key] = $replied_messages;

            // Mark original as answered
            $this->rc->storage->set_flag($original->uid, 'ANSWERED', $original->folder);

            // Save to sent folder
            $sent_mbox = $this->rc->config->get('sent_mbox', 'Sent');
            if (!$this->rc->config->get('no_save_sent_messages')) {
                $msg = $MAIL_MIME->getMessage();
                $this->rc->storage->save_message($sent_mbox, $msg);
            }

            rcube::write_log('ai_autoreply', "Auto-sent reply for message UID {$original->uid} to {$reply_to}");
        } else {
            $error_msg = is_string($smtp_error) ? $smtp_error : 'Unknown error';
            rcube::write_log('ai_autoreply', "Failed to auto-send reply: {$error_msg}");
        }

        // Clean up temp file
        if ($mailbody_file && file_exists($mailbody_file)) {
            @unlink($mailbody_file);
        }

        return (bool) $sent;
    }

    /**
     * Hook handler for preferences_list - add plugin settings.
     *
     * @param array $args Hook arguments
     *
     * @return array Modified arguments
     */
    public function preferences_list($args)
    {
        if ($args['section'] !== 'compose') {
            return $args;
        }

        $this->load_config();
        $this->add_texts('localization');

        $dont_override = $this->rc->config->get('dont_override', []);

        // Create AI Auto-Reply settings block
        $args['blocks']['ai_autoreply'] = [
            'name' => $this->gettext('ai_autoreply_settings'),
            'options' => [],
        ];

        // Enable/disable checkbox
        if (!in_array('ai_autoreply_enabled', $dont_override)) {
            $field_id = 'ai_autoreply_enabled';
            $checkbox = new html_checkbox(['name' => '_' . $field_id, 'id' => $field_id, 'value' => 1]);

            $args['blocks']['ai_autoreply']['options'][$field_id] = [
                'title' => html::label($field_id, $this->gettext('ai_autoreply_enable')),
                'content' => $checkbox->show($this->rc->config->get('ai_autoreply_enabled', false) ? 1 : 0),
            ];
        }

        // Auto-send checkbox
        if (!in_array('ai_autoreply_autosend', $dont_override)) {
            $field_id = 'ai_autoreply_autosend';
            $checkbox = new html_checkbox(['name' => '_' . $field_id, 'id' => $field_id, 'value' => 1]);

            $args['blocks']['ai_autoreply']['options'][$field_id] = [
                'title' => html::label($field_id, $this->gettext('ai_autoreply_autosend')),
                'content' => $checkbox->show($this->rc->config->get('ai_autoreply_autosend', false) ? 1 : 0)
                    . html::span(['class' => 'input-group-append'], html::span(['class' => 'input-group-text warning'], $this->gettext('ai_autoreply_autosend_warning'))),
            ];
        }

        // OpenAI API key
        if (!in_array('ai_autoreply_openai_key', $dont_override)) {
            $field_id = 'ai_autoreply_openai_key';
            $input = new html_passwordfield([
                'name' => '_' . $field_id,
                'id' => $field_id,
                'size' => 50,
                'autocomplete' => 'off',
            ]);

            $current_key = $this->rc->config->get('ai_autoreply_openai_key', '');
            $display_value = !empty($current_key) ? '********' : '';

            $args['blocks']['ai_autoreply']['options'][$field_id] = [
                'title' => html::label($field_id, $this->gettext('ai_autoreply_api_key')),
                'content' => $input->show($display_value),
            ];
        }

        return $args;
    }

    /**
     * Hook handler for preferences_save - save plugin settings.
     *
     * @param array $args Hook arguments
     *
     * @return array Modified arguments
     */
    public function preferences_save($args)
    {
        if ($args['section'] !== 'compose') {
            return $args;
        }

        $args['prefs']['ai_autoreply_enabled'] = (bool) rcube_utils::get_input_value('_ai_autoreply_enabled', rcube_utils::INPUT_POST);
        $args['prefs']['ai_autoreply_autosend'] = (bool) rcube_utils::get_input_value('_ai_autoreply_autosend', rcube_utils::INPUT_POST);

        // Handle API key - only update if changed (not the masked value)
        $api_key = rcube_utils::get_input_value('_ai_autoreply_openai_key', rcube_utils::INPUT_POST);
        if (!empty($api_key) && $api_key !== '********') {
            $args['prefs']['ai_autoreply_openai_key'] = $api_key;
        }

        return $args;
    }
}
