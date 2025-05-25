// twilio-whatsapp.js
require('dotenv').config();
const express = require('express');
const bodyParser = require('body-parser');
const axios = require('axios');
const { Twilio } = require('twilio');
const multer = require('multer');
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

// Configuration
const PORT = process.env.PORT || 3000;
const RAG_API_URL = process.env.RAG_API_URL || 'http://localhost:5001';
const TWILIO_ACCOUNT_SID = process.env.TWILIO_ACCOUNT_SID;
const TWILIO_AUTH_TOKEN = process.env.TWILIO_AUTH_TOKEN;
const TWILIO_PHONE_NUMBER = process.env.TWILIO_PHONE_NUMBER; // Should be in format: whatsapp:+14155238886
const WELFARE_NOTIFY_NUMBER = process.env.WELFARE_NOTIFY_NUMBER || 'whatsapp:+60123456789';
const TEMP_DIR = './temp-files';

// Verify required environment variables
if (!TWILIO_ACCOUNT_SID || !TWILIO_AUTH_TOKEN || !TWILIO_PHONE_NUMBER) {
  console.error('ERROR: Missing required Twilio configuration!');
  console.error(`TWILIO_ACCOUNT_SID: ${TWILIO_ACCOUNT_SID ? 'Set' : 'MISSING'}`);
  console.error(`TWILIO_AUTH_TOKEN: ${TWILIO_AUTH_TOKEN ? 'Set' : 'MISSING'}`);
  console.error(`TWILIO_PHONE_NUMBER: ${TWILIO_PHONE_NUMBER ? 'Set' : 'MISSING'}`);
  // Continue with warnings
}

// Initialize Express app
const app = express();

// Set up body parser middleware
app.use(bodyParser.urlencoded({ extended: false }));
app.use(bodyParser.json());

// Configure multer for file handling
const storage = multer.diskStorage({
  destination: function (req, file, cb) {
    if (!fs.existsSync(TEMP_DIR)) {
      fs.mkdirSync(TEMP_DIR, { recursive: true });
    }
    cb(null, TEMP_DIR);
  },
  filename: function (req, file, cb) {
    const uniqueSuffix = Date.now() + '-' + crypto.randomBytes(6).toString('hex');
    cb(null, uniqueSuffix + '-' + file.originalname);
  }
});
const upload = multer({ storage: storage });

// Initialize Twilio client
const twilioClient = new Twilio(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN);

// Health check endpoint
app.get('/health', (req, res) => {
  res.status(200).json({ status: 'healthy', timestamp: new Date().toISOString() });
});

// Function to check if document type is supported
function isSupportedDocumentType(mimeType, fileName) {
  if (mimeType === 'application/pdf') {
    return 'pdf';
  }
  
  if (mimeType === 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' ||
      /\.docx$/i.test(fileName)) {
    return 'docx';
  }
  
  if (mimeType === 'application/msword' || /\.doc$/i.test(fileName)) {
    return 'doc';
  }
  
  return false;
}

// Function to detect welfare reports for Selangor
async function checkForWelfareReports(messageContent, senderName, senderId) {
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
⏰ *Masa:* ${new Date().toLocaleString('ms-MY')}

📝 *Isi Mesej:*
${messageContent.substring(0, 300)}${messageContent.length > 300 ? '...' : ''}`;
      
      // Send notification via Twilio
      await twilioClient.messages.create({
        body: notificationMsg,
        from: TWILIO_PHONE_NUMBER,
        to: WELFARE_NOTIFY_NUMBER
      });
      
      console.log(`Welfare notification sent to ${WELFARE_NOTIFY_NUMBER}`);
      return true;
    } catch (error) {
      console.error(`Error sending welfare notification: ${error.message}`);
    }
  }
  
  return false;
}

// Process document in RAG
async function processDocumentInRag(docData) {
  try {
    console.log(`Processing ${docData.docType.toUpperCase()} in RAG: ${docData.fileName}`);
    
    // Send to RAG API
    const response = await axios.post(`${RAG_API_URL}/process-document`, {
      messageId: docData.messageId,
      sender: docData.sender,
      senderName: docData.senderName,
      documentData: docData.documentData,
      fileName: docData.fileName,
      timestamp: docData.timestamp,
      isGroup: false // Twilio doesn't have the concept of groups like direct WhatsApp
    }, {
      timeout: 300000, // 5 minute timeout for large documents
      maxBodyLength: 100 * 1024 * 1024, // 100MB max size
      headers: {
        'Content-Type': 'application/json'
      }
    });
    
    console.log(`${docData.docType.toUpperCase()} processing response:`, response.data);
    
    // Prepare success message
    let successMessage = `✅ ${docData.docType.toUpperCase()} processed successfully!\n\n`;
    successMessage += `📄 Document: ${docData.fileName}\n`;
    successMessage += `📑 Pages processed: ${response.data.pages_processed}\n`;
    
    if (response.data.chunks_processed) {
      successMessage += `🔍 Text chunks: ${response.data.chunks_processed}\n`;
    }
    
    successMessage += `\nYou can now ask questions about this document using:\n/ask [your question]`;
    
    // Check if document contains welfare reports for Selangor
    const upperFileName = docData.fileName.toUpperCase();
    if ((upperFileName.includes('KEBAJIKAN') || upperFileName.includes('WELFARE')) && 
        upperFileName.includes('SELANGOR')) {
      try {
        // Send welfare notification for relevant document
        const notificationMsg = `🔔 *Pemberitahuan Dokumen Kebajikan Selangor*
        
Dokumen berkaitan kebajikan Selangor telah diproses:

📄 *Nama Dokumen:* ${docData.fileName}
👤 *Dihantar Oleh:* ${docData.senderName || 'Tidak diketahui'}
⏰ *Masa:* ${new Date().toLocaleString('ms-MY')}
📊 *Halaman:* ${response.data.pages_processed || 'Tidak diketahui'}`;
        
        // Send notification via Twilio
        await twilioClient.messages.create({
          body: notificationMsg,
          from: TWILIO_PHONE_NUMBER,
          to: WELFARE_NOTIFY_NUMBER
        });
        
        console.log(`Welfare document notification sent to ${WELFARE_NOTIFY_NUMBER}`);
      } catch (notifyError) {
        console.error(`Error sending welfare document notification: ${notifyError.message}`);
      }
    }
    
    return { success: true, message: successMessage, data: response.data };
  } catch (error) {
    console.error(`Error processing document in RAG:`, error);
    
    // Log more detailed error information
    if (error.response) {
      console.error("Error response data:", JSON.stringify(error.response.data));
      console.error("Error response status:", error.response.status);
      console.error("Error response headers:", error.response.headers);
    }
    
    let errorMessage = `Error processing ${docData.docType.toUpperCase()}.`;
    if (error.response && error.response.data) {
      if (typeof error.response.data === 'object') {
        errorMessage += ` ${error.response.data.error || error.response.data.message || JSON.stringify(error.response.data)}`;
      } else {
        errorMessage += ` ${error.response.data}`;
      }
    } else {
      errorMessage += ` ${error.message}`;
    }
    
    return { success: false, message: errorMessage };
  }
}

// Store message in RAG
async function storeMessageInRag(messageData) {
  try {
    console.log(`Storing message in RAG: "${messageData.content}"`);
    
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
    return { success: false, error: error.message };
  }
}

// Handle RAG query
async function handleRagQuery(queryData) {
  try {
    console.log(`Processing RAG query: "${queryData.query}"`);
    
    const response = await axios.post(`${RAG_API_URL}/query-rag`, { query: queryData.query }, {
      timeout: 30000 // 30 second timeout
    });
    
    console.log('RAG API response:', response.data);
    
    const answer = response.data.answer || 'Sorry, I couldn\'t find an answer to that.';
    return { success: true, answer };
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
    
    return { success: false, error: errorMessage };
  }
}

// Main webhook for incoming WhatsApp messages
app.post('/webhook', async (req, res) => {
  try {
    // Respond to Twilio immediately to avoid timeouts
    res.status(200).send('OK');
    
    console.log('Incoming message:', req.body);
    
    // Extract message information
    const from = req.body.From;
    const to = req.body.To;
    const body = req.body.Body || '';
    const numMedia = parseInt(req.body.NumMedia || '0');
    const messageSid = req.body.MessageSid;
    const profileName = req.body.ProfileName || 'Unknown';
    
    // Generate timestamp
    const timestamp = Math.floor(Date.now() / 1000);
    
    console.log(`Message from ${profileName} (${from}): ${body}`);
    
    // Check for media attachments
    if (numMedia > 0) {
      // Handle media (PDF, DOCX, etc.)
      for (let i = 0; i < numMedia; i++) {
        const contentType = req.body[`MediaContentType${i}`];
        const mediaUrl = req.body[`MediaUrl${i}`];
        
        // Generate a better filename based on content type if original filename is missing
        let mediaFilename = req.body[`MediaFilename${i}`];
        if (!mediaFilename) {
          // Create a more descriptive default filename based on content type
          if (contentType === 'application/pdf') {
            mediaFilename = `document-${Date.now()}.pdf`;
          } else if (contentType === 'application/vnd.openxmlformats-officedocument.wordprocessingml.document') {
            mediaFilename = `document-${Date.now()}.docx`;
          } else if (contentType === 'application/msword') {
            mediaFilename = `document-${Date.now()}.doc`;
          } else {
            mediaFilename = `file-${i}-${Date.now()}.bin`;
          }
        }
        
        console.log(`Received media: ${mediaFilename} (${contentType})`);
        
        const docType = isSupportedDocumentType(contentType, mediaFilename);
        
        if (docType) {
          console.log(`Processing ${docType.toUpperCase()} file: ${mediaFilename}`);
          
          try {
            // Send acknowledgement
            await twilioClient.messages.create({
              body: `📄 Received ${docType.toUpperCase()}: ${mediaFilename}\nProcessing document, please wait...`,
              from: to,
              to: from
            });
            
            // Download media file with proper authentication
            console.log(`Downloading media from URL: ${mediaUrl}`);
            console.log(`Using auth with Account SID: ${TWILIO_ACCOUNT_SID.substring(0, 5)}...`);
            
            const mediaResponse = await axios.get(mediaUrl, { 
              responseType: 'arraybuffer',
              auth: {
                username: TWILIO_ACCOUNT_SID,
                password: TWILIO_AUTH_TOKEN
              }
            });
            
            console.log(`Downloaded media file successfully: ${mediaResponse.data.byteLength} bytes`);
            const documentData = Buffer.from(mediaResponse.data).toString('base64');
            
            // Process document
            const processResult = await processDocumentInRag({
              messageId: messageSid,
              sender: from,
              senderName: profileName,
              documentData,
              fileName: mediaFilename,
              timestamp,
              docType
            });
            
            // Send response
            await twilioClient.messages.create({
              body: processResult.message,
              from: to,
              to: from
            });
          } catch (error) {
            console.error(`Error processing document:`, error);
            
            // Send error message
            await twilioClient.messages.create({
              body: `❌ Error processing ${docType.toUpperCase()}: ${error.message}`,
              from: to,
              to: from
            });
          }
        } else {
          await twilioClient.messages.create({
            body: `❌ Unsupported file type: ${mediaFilename}. Only PDF and DOCX files are supported.`,
            from: to,
            to: from
          });
        }
      }
    } else {
      // Handle text messages
      
      // Check for welfare reports
      await checkForWelfareReports(body, profileName, from);
      
      // Check if message is a RAG query
      if (body.trim().toLowerCase().startsWith('/ask')) {
        const query = body.substring(4).trim();
        
        if (query === '') {
          await twilioClient.messages.create({
            body: 'Please specify a question after /ask',
            from: to,
            to: from
          });
        } else {
          // Process RAG query
          const queryResult = await handleRagQuery({
            query,
            sender: from,
            timestamp
          });
          
          // Send response
          await twilioClient.messages.create({
            body: queryResult.success ? queryResult.answer : queryResult.error,
            from: to,
            to: from
          });
        }
      } else {
        // Store normal message in RAG
        await storeMessageInRag({
          messageId: messageSid,
          sender: from,
          senderName: profileName,
          content: body,
          timestamp,
          isGroup: false
        });
        
        // Optional: You can send an acknowledgement or let the user know the message was stored
        // For most bots, you'd only reply to commands
      }
    }
  } catch (error) {
    console.error('Error processing webhook:', error);
  }
});

// Start the server
app.listen(PORT, () => {
  console.log(`Twilio WhatsApp webhook server running on port ${PORT}`);
});

// Check RAG API health on startup and periodically
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

// Perform initial health check
(async function initialize() {
  try {
    // Check API health first
    const apiHealthy = await checkApiHealth();
    if (!apiHealthy) {
      console.warn('⚠️ WARNING: RAG API is not responding correctly');
      console.warn('The Twilio webhook server will still start, but message processing may fail');
    } else {
      console.log('✅ RAG API health check passed');
    }
  } catch (error) {
    console.error('Initialization error:', error);
  }
})();

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
