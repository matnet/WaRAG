// Load crypto polyfill FIRST before any other imports
require('./crypto-polyfill');

const { default: makeWASocket, DisconnectReason, useMultiFileAuthState, downloadContentFromMessage } = require('@whiskeysockets/baileys');
const { Boom } = require('@hapi/boom');
const qrcode = require('qrcode-terminal');
const fs = require('fs');
const axios = require('axios');
const dotenv = require('dotenv');
const path = require('path');

// Load environment variables
dotenv.config();

// Configuration
const RAG_API_URL = process.env.RAG_API_URL || 'http://localhost:5001';
const SESSION_DIR = './whatsapp-sessions';
const TEMP_DIR = './temp-files';
const WELFARE_NOTIFY_JID = '6012345678@s.whatsapp.net'; // Nombor untuk pemberitahuan kebajikan

// Debug: Print configuration
console.log(`Using RAG API URL: ${RAG_API_URL}`);

// Ensure directories exist
if (!fs.existsSync(SESSION_DIR)) {
    fs.mkdirSync(SESSION_DIR, { recursive: true });
    console.log(`Created session directory: ${SESSION_DIR}`);
}
if (!fs.existsSync(TEMP_DIR)) {
    fs.mkdirSync(TEMP_DIR, { recursive: true });
    console.log(`Created temp directory: ${TEMP_DIR}`);
}

// Cache for group participants to help with session management
const groupParticipantsCache = {};

// Check if document type is supported
function isSupportedDocumentType(mimeType, fileName) {
    // Check for supported document types
    if (mimeType === 'application/pdf') {
        return 'pdf';
    }
    
    // Check for DOCX and DOC files
    if (mimeType === 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' ||
        /\.docx$/i.test(fileName)) {
        return 'docx';
    }
    
    if (mimeType === 'application/msword' || /\.doc$/i.test(fileName)) {
        return 'doc';
    }
    
    return false;
}

// Function to detect welfare reports for Selangor and notify specific user
async function checkForWelfareReports(messageContent, senderName, senderId, remoteJid, sock) {
    // Skip if message is empty
    if (!messageContent || messageContent.trim() === '') return false;
    
    // Convert message to uppercase for case-insensitive matching
    const upperContent = messageContent.toUpperCase();
    
    // Check if message contains welfare report keywords and "SELANGOR"
    const hasWelfareKeywords = (
        upperContent.includes("LAWATAN KEBAJIKAN") || 
        upperContent.includes("LAPORAN KEBAJIKAN")
    );
    
    const hasSelangor = upperContent.includes("SELANGOR");
    
    // If both conditions are met, send notification
    if (hasWelfareKeywords && hasSelangor) {
        console.log("Detected welfare report for Selangor!");
        
        try {
            // Prepare notification message
            const notificationMsg = `🔔 *Pemberitahuan Kebajikan Selangor*
            
Mesej berkaitan kebajikan Selangor telah dikesan:

👤 *Pengirim:* ${senderName}
👤 *ID Pengirim:* ${senderId}
🗣️ *Dari:* ${remoteJid.endsWith('@g.us') ? 'Grup WhatsApp' : 'Chat Peribadi'}
⏰ *Masa:* ${new Date().toLocaleString('ms-MY')}

📝 *Isi Mesej:*
${messageContent.substring(0, 300)}${messageContent.length > 300 ? '...' : ''}`;
            
            // Send notification
            await sock.sendMessage(WELFARE_NOTIFY_JID, {
                text: notificationMsg
            });
            
            console.log(`Welfare notification sent to ${WELFARE_NOTIFY_JID}`);
            return true;
        } catch (error) {
            console.error(`Error sending welfare notification: ${error.message}`);
        }
    }
    
    return false;
}

// Utility function: Retry with delay
async function retryWithDelay(fn, maxRetries = 3, delayMs = 1000) {
    let lastError;
    
    for (let attempt = 1; attempt <= maxRetries; attempt++) {
        try {
            return await fn();
        } catch (err) {
            console.log(`Attempt ${attempt}/${maxRetries} failed: ${err.message}`);
            lastError = err;
            
            // If it's not the last attempt, wait before retrying
            if (attempt < maxRetries) {
                console.log(`Waiting ${delayMs}ms before retry...`);
                await new Promise(resolve => setTimeout(resolve, delayMs));
            }
        }
    }
    
    throw lastError; // Re-throw the last error if all attempts fail
}

// Function to fetch group metadata including participants
async function updateGroupParticipants(jid, sock) {
    try {
        if (!jid.endsWith('@g.us')) return;
        
        console.log(`Updating group participants for ${jid}`);
        const metadata = await sock.groupMetadata(jid);
        
        if (metadata && metadata.participants) {
            groupParticipantsCache[jid] = metadata.participants.map(p => ({
                id: p.id,
                admin: p.admin
            }));
            console.log(`Updated group cache with ${groupParticipantsCache[jid].length} participants`);
        }
    } catch (err) {
        console.error(`Error fetching group participants: ${err.message}`);
    }
}

// Connect to WhatsApp
async function connectToWhatsApp() {
    // Authentication state
    const { state, saveCreds } = await useMultiFileAuthState(SESSION_DIR);
    console.log('Loaded auth state');
    
    // Create WhatsApp socket connection
    const sock = makeWASocket({
        auth: state,
        printQRInTerminal: true,
        defaultQueryTimeoutMs: 60000, // Increase timeout
        connectTimeoutMs: 60000,
        keepAliveIntervalMs: 25000,
        retryRequestDelayMs: 2000,
    });
    
    // Save credentials on update
    sock.ev.on('creds.update', saveCreds);
    
    // Handle connection updates
    sock.ev.on('connection.update', async (update) => {
        const { connection, lastDisconnect, qr } = update;
        
        // Display QR code if needed
        if (qr) {
            console.log('\nScan this QR code with WhatsApp to log in:');
        }
        
        if (connection === 'close') {
            const shouldReconnect = 
                (lastDisconnect?.error instanceof Boom)? 
                lastDisconnect.error.output.statusCode !== DisconnectReason.loggedOut : 
                true;
            
            console.log('Connection closed due to ', lastDisconnect?.error, 'Reconnecting:', shouldReconnect);
            
            if (shouldReconnect) {
                console.log('Attempting to reconnect...');
                connectToWhatsApp();
            } else {
                console.log('Not reconnecting due to logout');
            }
        } else if (connection === 'open') {
            console.log('WhatsApp connection established!');
            
            // Preload participant lists for any saved groups
            try {
                const chats = await sock.groupFetchAllParticipating();
                for (const [key, value] of Object.entries(chats)) {
                    groupParticipantsCache[key] = value.participants;
                    console.log(`Preloaded ${value.participants.length} participants for group ${key}`);
                }
            } catch (err) {
                console.error('Error preloading group participants:', err.message);
            }
        }
    });
    
    // Listen for group updates
    sock.ev.on('group.update', async (update) => {
        const { id } = update;
        if (id) {
            await updateGroupParticipants(id, sock);
        }
    });
    
    // Process messages
    sock.ev.on('messages.upsert', async (messagesUpsert) => {
        console.log(`Received message update of type: ${messagesUpsert.type}`);
        
        if (messagesUpsert.type !== 'notify') {
            console.log('Ignoring non-notify message update');
            return;
        }
        
        console.log(`Processing ${messagesUpsert.messages.length} new messages`);
        
        for (const msg of messagesUpsert.messages) {
            // Skip status messages and message receipt notifications
            if (msg.key.remoteJid === 'status@broadcast') {
                console.log('Skipping status broadcast message');
                continue;
            }
            
            // Skip messages sent by me to avoid processing loops
            if (msg.key.fromMe) {
                console.log('Skipping message sent by me');
                continue;
            }
            
            // Process chat message
            console.log('Processing incoming message');
            await processMessage(msg, sock);
        }
    });
    
    return sock;
}

// Process incoming messages
async function processMessage(msg, sock) {
    try {
        // Get message details
        const remoteJid = msg.key.remoteJid;
        const isGroup = remoteJid.endsWith('@g.us');
        const senderId = msg.key.participant || remoteJid;
        const senderName = msg.pushName || 'Unknown';
        const messageId = msg.key.id;
        
        console.log(`Message from ${senderName} (${senderId}), isGroup: ${isGroup}`);
        
        // Update group participants cache if this is a group
        if (isGroup && !groupParticipantsCache[remoteJid]) {
            await updateGroupParticipants(remoteJid, sock);
        }
        
        // Check for document
        if (msg.message?.documentMessage) {
            const docMessage = msg.message.documentMessage;
            console.log(`Received document: ${docMessage.fileName} (${docMessage.mimetype})`);
            
            // Check if document type is supported
            const docType = isSupportedDocumentType(docMessage.mimetype, docMessage.fileName);
            
            if (docType) {
                console.log(`Processing ${docType.toUpperCase()} file: ${docMessage.fileName}`);
                
                // Send acknowledgment
                await sock.sendMessage(remoteJid, {
                    text: `📄 Received ${docType.toUpperCase()}: ${docMessage.fileName}\nProcessing document, please wait...`
                });
                
                try {
                    // Download document file with retries
                    console.log('Downloading document file...');
                    const docBuffer = await downloadDocument(docMessage, sock, 3);
                    console.log(`Downloaded document file (${docBuffer.length} bytes)`);
                    
                    // Only continue if we got a valid buffer with content
                    if (!docBuffer || docBuffer.length < 100) {
                        throw new Error('Downloaded document appears to be empty or invalid');
                    }
                    
                    // Convert to base64
                    const docBase64 = docBuffer.toString('base64');
                    console.log('Converted document to base64');
                    
                    // Send document to RAG API for processing
                    console.log('Sending document to RAG API for processing');
                    await processDocumentInRag({
                        messageId: messageId,
                        sender: senderId,
                        senderName: senderName,
                        documentData: docBase64,
                        fileName: docMessage.fileName,
                        timestamp: msg.messageTimestamp,
                        isGroup: isGroup
                    }, remoteJid, sock, docType);
                    
                } catch (error) {
                    console.error(`Error processing ${docType.toUpperCase()}:`, error);
                    let errorMsg = `Error processing ${docType.toUpperCase()}. `;
                    
                    // Provide more specific error messages for different error types
                    if (error.name === 'SessionError' || error.message.includes('session')) {
                        errorMsg += 'There was a WhatsApp encryption error. Please try sending the document again or send it as a private message.';
                    } else if (error.message.includes('ECONNREFUSED') || error.message.includes('ECONNRESET')) {
                        errorMsg += 'Could not connect to the processing service. Please try again later.';
                    } else {
                        errorMsg += error.message;
                    }
                    
                    await sock.sendMessage(remoteJid, {
                        text: `❌ ${errorMsg}`
                    });
                }
                return;
            }
        }
        
        // Extract message content with robust handling
        let messageContent = '';
        let messageType = 'unknown';
        
        if (msg.message?.conversation && msg.message.conversation.trim() !== '') {
            messageContent = msg.message.conversation;
            messageType = 'conversation';
        } 
        else if (msg.message?.extendedTextMessage?.text && msg.message.extendedTextMessage.text.trim() !== '') {
            messageContent = msg.message.extendedTextMessage.text;
            messageType = 'extendedTextMessage';
        } 
        else if (msg.message?.imageMessage?.caption && msg.message.imageMessage.caption.trim() !== '') {
            messageContent = msg.message.imageMessage.caption;
            messageType = 'imageMessage';
        } 
        else if (msg.message?.videoMessage?.caption && msg.message.videoMessage.caption.trim() !== '') {
            messageContent = msg.message.videoMessage.caption;
            messageType = 'videoMessage';
        }
        else if (msg.message?.documentMessage?.caption && msg.message.documentMessage.caption.trim() !== '') {
            messageContent = msg.message.documentMessage.caption;
            messageType = 'documentMessage';
        }
        
        // Log extracted content
        console.log(`Message type: ${messageType}, Content: "${messageContent}"`);
        
        // Check for welfare reports related to Selangor (NEW FEATURE)
        const isWelfareReport = await checkForWelfareReports(
            messageContent, 
            senderName, 
            senderId, 
            remoteJid, 
            sock
        );
        
        if (isWelfareReport) {
            console.log('Processed welfare report notification');
        }
        
        // Check if there's a message to process
        if (messageContent.trim() === '') {
            console.log('No text content to process');
            return;
        }
        
        // Check if message is a RAG query
        if (messageContent.trim().toLowerCase().startsWith('/ask')) {
            console.log('Detected /ask command');
            const query = messageContent.substring(4).trim();
            
            if (query === '') {
                console.log('Empty query detected');
                await sock.sendMessage(remoteJid, {
                    text: 'Please specify a question after /ask'
                });
                return;
            }
            
            console.log(`Processing query: "${query}"`);
            await handleRagQuery(query, remoteJid, sock);
            return;
        }
        
        // Store normal text messages in the RAG system
        console.log(`Storing message in RAG: "${messageContent}"`);
        
        // Store message in RAG
        const storeResult = await storeMessageInRag({
            messageId: messageId,
            sender: senderId,
            senderName: senderName,
            content: messageContent,
            timestamp: msg.messageTimestamp,
            isGroup: isGroup
        });
        
        console.log(`Message storage result: ${JSON.stringify(storeResult)}`);
        
    } catch (error) {
        console.error('Error processing message:', error);
        console.error('Error stack:', error.stack);
        if (error.response) {
            console.error('API error response:', error.response.data);
        }
    }
}

// Download document from WhatsApp with retry logic
async function downloadDocument(documentMessage, sock, retryCount = 3) {
    console.log('Starting document download...');
    
    try {
        // Download as stream with retries
        return await retryWithDelay(async () => {
            const stream = await downloadContentFromMessage(documentMessage, 'document');
            
            // Convert stream to buffer
            let buffer = Buffer.from([]);
            
            for await (const chunk of stream) {
                buffer = Buffer.concat([buffer, chunk]);
                console.log(`Downloaded chunk (total: ${buffer.length} bytes)`);
            }
            
            console.log(`Download complete: ${buffer.length} bytes`);
            return buffer;
        }, retryCount, 2000);
    } catch (error) {
        console.error('Error downloading document:', error);
        
        // Check if it's a session error and log more details
        if (error.name === 'SessionError' || error.message.includes('session')) {
            console.error('Session error detected during document download. This may be due to WhatsApp encryption keys needing to be refreshed.');
            
            // Log additional debugging info
            if (documentMessage.participant) {
                console.log(`Document from participant: ${documentMessage.participant}`);
            }
        }
        
        throw new Error(`Failed to download document: ${error.message}`);
    }
}

// Process any document with RAG API
async function processDocumentInRag(docData, remoteJid, sock, docType = 'document') {
    try {
        console.log(`Processing ${docType.toUpperCase()} in RAG: ${docData.fileName}`);
        
        // Send to RAG API
        const response = await axios.post(`${RAG_API_URL}/process-document`, docData, {
            timeout: 300000, // 5 minute timeout for large documents
            maxBodyLength: 100 * 1024 * 1024, // 100MB max size
            headers: {
                'Content-Type': 'application/json'
            }
        });
        
        console.log(`${docType.toUpperCase()} processing response:`, response.data);
        
        // Send success message
        await sock.sendMessage(remoteJid, {
            text: `✅ ${docType.toUpperCase()} processed successfully!\n\n📄 Document: ${docData.fileName}\n📑 Pages processed: ${response.data.pages_processed}\n${response.data.chunks_processed ? '🔍 Text chunks: ' + response.data.chunks_processed + '\n' : ''}\nYou can now ask questions about this document using:\n/ask [your question]`
        });
        
        // Check if document contains welfare reports for Selangor (NEW FEATURE)
        const fileName = docData.fileName || '';
        const upperFileName = fileName.toUpperCase();
        
        if ((upperFileName.includes('KEBAJIKAN') || upperFileName.includes('WELFARE')) && 
             upperFileName.includes('SELANGOR')) {
            try {
                // Send welfare notification for relevant document
                const notificationMsg = `🔔 *Pemberitahuan Dokumen Kebajikan Selangor*
                
Dokumen berkaitan kebajikan Selangor telah diproses:

📄 *Nama Dokumen:* ${docData.fileName}
👤 *Dihantar Oleh:* ${docData.senderName}
🗣️ *Dari:* ${remoteJid.endsWith('@g.us') ? 'Grup WhatsApp' : 'Chat Peribadi'}
⏰ *Masa:* ${new Date().toLocaleString('ms-MY')}
📊 *Halaman:* ${response.data.pages_processed || 'Tidak diketahui'}`;
                
                // Send notification
                await sock.sendMessage(WELFARE_NOTIFY_JID, {
                    text: notificationMsg
                });
                
                console.log(`Welfare document notification sent to ${WELFARE_NOTIFY_JID}`);
            } catch (notifyError) {
                console.error(`Error sending welfare document notification: ${notifyError.message}`);
            }
        }
        
        return response.data;
    } catch (error) {
        console.error(`Error processing ${docType.toUpperCase()} in RAG:`, error);
        
        let errorMessage = `Error processing ${docType.toUpperCase()}.`;
        if (error.response && error.response.data) {
            errorMessage += ` ${error.response.data.error || JSON.stringify(error.response.data)}`;
        } else {
            errorMessage += ` ${error.message}`;
        }
        
        await sock.sendMessage(remoteJid, {
            text: `❌ ${errorMessage}`
        });
        
        throw error;
    }
}

// Process PDF with RAG API (for backward compatibility)
async function processPdfInRag(pdfData, remoteJid, sock) {
    // Rename pdfData to documentData for the new endpoint
    const docData = { ...pdfData };
    docData.documentData = pdfData.pdfData;
    delete docData.pdfData;
    
    return processDocumentInRag(docData, remoteJid, sock, 'pdf');
}

// Store message in RAG system
async function storeMessageInRag(messageData) {
    try {
        console.log(`Making API call to ${RAG_API_URL}/store-message`);
        console.log('Message data:', JSON.stringify(messageData));
        
        const response = await axios.post(`${RAG_API_URL}/store-message`, messageData, {
            timeout: 10000, // 10 second timeout
            headers: {
                'Content-Type': 'application/json'
            }
        });
        
        console.log('Message stored in RAG, response:', response.data);
        return { success: true, data: response.data };
    } catch (error) {
        console.error('Error storing message in RAG:', error.message);
        if (error.response) {
            console.error('Error response data:', error.response.data);
        } else if (error.request) {
            console.error('No response received', error.request);
        } else {
            console.error('Error setting up request', error.message);
        }
        return { success: false, error: error.message };
    }
}

// Handle RAG query
async function handleRagQuery(query, remoteJid, sock) {
    if (!query) {
        await sock.sendMessage(remoteJid, { text: 'Please specify a question after /ask' });
        return;
    }
    
    console.log(`Processing RAG query: "${query}"`);
    
    try {
        // Send typing indicator
        await sock.presenceSubscribe(remoteJid);
        await sock.sendPresenceUpdate('composing', remoteJid);
        
        console.log(`Making API call to ${RAG_API_URL}/query-rag`);
        const response = await axios.post(`${RAG_API_URL}/query-rag`, { query }, {
            timeout: 30000 // 30 second timeout
        });
        
        console.log('RAG API response:', response.data);
        
        const answer = response.data.answer || 'Sorry, I couldn\'t find an answer to that.';
        
        // Stop typing indicator
        await sock.sendPresenceUpdate('paused', remoteJid);
        
        // Send the answer
        await sock.sendMessage(remoteJid, { text: answer });
        console.log(`Sent RAG response: "${answer.substring(0, 100)}${answer.length > 100 ? '...' : ''}"`);
    } catch (error) {
        console.error('Error querying RAG system:', error.message);
        
        let errorMessage = 'Sorry, I encountered an error while processing your question.';
        
        if (error.response) {
            console.error('Error response data:', error.response.data);
            errorMessage += ` (API error: ${error.response.status})`;
        } else if (error.request) {
            console.error('No response received from API');
            errorMessage += ' (No response from API)';
        }
        
        await sock.sendMessage(remoteJid, { 
            text: errorMessage
        });
    }
}

// Health check function to verify API connectivity
async function checkApiHealth() {
    try {
        console.log(`Checking RAG API health at ${RAG_API_URL}/health`);
        const response = await axios.get(`${RAG_API_URL}/health`, {
            timeout: 5000
        });
        console.log('API health response:', response.data);
        return response.data.status === 'healthy';
    } catch (error) {
        console.error('API health check failed:', error.message);
        return false;
    }
}

// Perform initial health check and start WhatsApp client
async function initialize() {
    try {
        // Check API health first
        const apiHealthy = await checkApiHealth();
        if (!apiHealthy) {
            console.warn('⚠️ WARNING: RAG API is not responding correctly');
            console.warn('The WhatsApp client will still start, but message processing may fail');
        } else {
            console.log('✅ RAG API health check passed');
        }
        
        // Start WhatsApp client
        connectToWhatsApp();
        
    } catch (error) {
        console.error('Initialization error:', error);
    }
}

// Start the application
initialize();

// Set up periodic health checks
setInterval(async () => {
    try {
        const healthy = await checkApiHealth();
        if (!healthy) {
            console.warn('⚠️ WARNING: RAG API is not responding during periodic health check');
        }
    } catch (error) {
        console.error('Error during periodic health check:', error);
    }
}, 5 * 60 * 1000); // Check every 5 minutes
