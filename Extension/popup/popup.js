document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll(".tab-content").forEach(el => el.style.display = "none");
    document.getElementById("fetch-content").style.display = "block"; // Show the first tab

    document.getElementById("fetch-tab").addEventListener("click", function () {
        showTab("fetch-content", "fetch-tab");
    });

    document.getElementById("logs-tab").addEventListener("click", function () {
        showTab("logs-content", "logs-tab");
        fetchEmailLogs();
    });

    function showTab(contentId, tabId) {
        document.querySelectorAll(".tab-content").forEach(el => el.style.display = "none");
        document.getElementById(contentId).style.display = "block";

        document.querySelectorAll(".nav-link").forEach(el => el.classList.remove("active"));
        document.getElementById(tabId).classList.add("active");
    }

    document.getElementById("fetch-emails").addEventListener("click", fetchEmails);
});

async function fetchEmails() {
    const emailList = document.getElementById("email-list");
    emailList.innerHTML = `
        <div class="text-center mt-3">
            <div class="spinner-border text-primary" role="status">
                <span class="visually-hidden">Loading...</span>
            </div>
            <p class="text-muted mt-2">Loading mails...</p>
        </div>
    `;


    try {
        const response = await fetch("http://localhost:5000/fetch-emails"); // Assuming API is running locally
        const emails = await response.json();
        console.log(emails, "mails");

        if (emails.length === 0) {
            emailList.innerHTML = "No new emails found.";
        } else {
            emailList.innerHTML = emails.map(email => `
                <div class="email-item card p-3">
                   <div class="email-details p-3 border rounded shadow-sm">
                   <p><strong class="text-primary">From:</strong> <span class="text-dark">${email.sender}</span></p>
                   <p><strong class="text-success">Subject:</strong> <span class="text-dark">${email.subject}</span></p>
                   <p><strong class="text-secondary">Snippet:</strong> <span class="text-muted">${email.snippet}</span></p>
                   </div>
                    ${email.full_body.trim() !== email.snippet.trim() ? `<button class="btn btn-sm btn-outline-primary view-full-btn" data-id="${email.id}">View Full Email</button>` : ""}
                    <div id="full-email-${email.id}" class="full-email-content" style="display: none;">
                        <p>${email.full_body}</p>
                    </div>
                    <div class="d-block mt-2">
                    <button class="btn btn-outline-primary reply-btn w-100" data-id="${email.id}" 
                        data-subject="${email.subject}" data-snippet="${email.snippet}"  
                        data-reply="${email.reply.replace(/"/g, '&quot;')}">
                        Reply
                    </button>
                    </div>
                    <div id="reply-box-${email.id}" class="reply-box mt-3 p-3 border rounded bg-light">
                        <textarea id="reply-text-${email.id}" class="form-control" rows="4">AI-generated reply here...</textarea>
                        <br>
                        <button class="btn btn-success send-reply-btn mt-2" data-to="${email.sender_email}" data-id="${email.id}">
                            Send
                        </button>
                    </div>
                </div>
            `).join('');

            document.querySelectorAll(".reply-btn").forEach(button => {
                button.addEventListener("click", (event) => {
                    toggleReplyBox(event.target.dataset.id, event.target.dataset.reply);
                });
            });

            document.querySelectorAll(".send-reply-btn").forEach(button => {
                button.addEventListener("click", function () {
                    const emailId = this.getAttribute("data-id");
                    sendReply(emailId);
                });  
            });
            document.querySelectorAll(".view-full-btn").forEach(button => {
                button.addEventListener("click", function () {
                    const emailId = this.getAttribute("data-id");
                    const fullEmailDiv = document.getElementById(`full-email-${emailId}`);
                    fullEmailDiv.style.display = fullEmailDiv.style.display === "none" ? "block" : "none";
                });
            });
        }
    } catch (error) {
        emailList.innerHTML = "Failed to fetch emails.";
    }
}

function toggleReplyBox(emailId, reply) {
    const replyBox = document.getElementById(`reply-box-${emailId}`);
    const replyText = document.getElementById(`reply-text-${emailId}`);

    if (replyBox.style.display === "none" || replyBox.style.display === "") {
        replyBox.style.display = "block";
        replyText.value = reply || "AI-generated reply here...";
    } else {
        replyBox.style.display = "none";
    }
}

function sendReply(emailId) {
    const replyText = document.getElementById(`reply-text-${emailId}`).value;
    const to = document.querySelector(`.send-reply-btn[data-id='${emailId}']`).getAttribute("data-to");
    const msg_id = document.querySelector(`.send-reply-btn[data-id='${emailId}']`).getAttribute("data-id");
    const subject = document.querySelector(`.reply-btn[data-id='${emailId}']`).getAttribute("data-subject");

    const confirmation = confirm(
        `Final Message Preview:\n\nTo: ${to}\n\nMessage:\n${replyText}\n\nDo you want to send this email?`
    );

    if (!confirmation) {
        alert("Email not sent.");
        return;
    }

    fetch("http://127.0.0.1:5000/send-email", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({msg_id, emailId, to, subject, reply: replyText })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            alert("Email sent successfully!");
        } else {
            alert("Failed to send email: " + data.error);
        }
    })
    .catch(error => console.error("Error sending email:", error));
}
function fetchEmailLogs() {
    let tableBody = document.getElementById("email-logs");
    let tableContainer = document.getElementById("table-container");

    tableContainer.style.visibility = "hidden"; // Hide while updating

    fetch("http://127.0.0.1:5000/email-logs")
    .then(response => response.json())
    .then(data => {
        tableBody.innerHTML = ""; // Clear existing rows

        data.forEach(log => {
            let row = document.createElement("tr");
            row.innerHTML = `
                <td>${log.subject}</td>
                <td>${log.sender_email}</td>
                <td>${log.received_time}</td>
                <td>${log.sent_time}</td>
            `;
            tableBody.appendChild(row);
        });

        tableContainer.style.visibility = "visible"; // Show when ready
    })
    .catch(error => console.error("Error fetching email logs:", error));
}


