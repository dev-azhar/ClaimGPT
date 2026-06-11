import {
  isStaticClaim,
  MOCK_CLAIMS,
  MOCK_PREVIEW_DATA,
  generateMockPdf,
  generateMockDocumentPdf,
  getMockChatResponse,
  getMockChatSuggestions,
} from "./mockClaimsData";

let isInitialized = false;

export function initializeMockInterceptor() {
  if (typeof window === "undefined" || isInitialized) return;
  isInitialized = true;

  console.log("🚀 ClaimGPT: Global Mock Interceptor Initialized (Monkeypatching window.fetch)");

  const originalFetch = window.fetch;

  window.fetch = async function (input, init) {
    const url = typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;
    const method = (init?.method || "GET").toUpperCase();

    // 1. Intercept /claims list (e.g. GET /ingress/claims or /claims)
    if (url.includes("/claims") && !url.includes("/claims/") && method === "GET") {
      console.log(`[ClaimGPT Interceptor] Mocking/Merging Claim List: ${url}`);
      try {
        // Attempt to load from real backend
        const response = await originalFetch(input, init);
        if (!response.ok) throw new Error("Backend not ok");
        const data = await response.json();

        let backendClaims: any[] = [];
        let totalCount = 0;

        if (Array.isArray(data)) {
          backendClaims = data;
          totalCount = data.length;
        } else if (data && Array.isArray(data.claims)) {
          backendClaims = data.claims;
          totalCount = data.total || data.claims.length;
        }

        // Merge backend claims and static claims, avoiding duplicates
        const staticIds = new Set(MOCK_CLAIMS.map((c) => c.id));
        const filteredBackend = backendClaims.filter((c: any) => c && c.id && !staticIds.has(c.id));

        const mergedClaims = [...MOCK_CLAIMS, ...filteredBackend];
        const mergedTotal = mergedClaims.length;

        const mergedData = Array.isArray(data)
          ? mergedClaims
          : { ...data, claims: mergedClaims, total: mergedTotal };

        return new Response(JSON.stringify(mergedData), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      } catch (err) {
        console.warn("[ClaimGPT Interceptor] Backend offline. Returning static claims list only.", err);
        // Backend is down, return static claims
        const fallbackData = { claims: MOCK_CLAIMS, total: MOCK_CLAIMS.length };
        return new Response(JSON.stringify(fallbackData), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
    }

    // 2. Intercept /tpa-list
    if (url.includes("/tpa-list") && method === "GET") {
      console.log(`[ClaimGPT Interceptor] Intercepting TPA list: ${url}`);
      try {
        const response = await originalFetch(input, init);
        if (response.ok) {
          return response;
        }
        throw new Error("Backend not ok");
      } catch (err) {
        console.warn("[ClaimGPT Interceptor] Backend offline or error. Returning static mock TPA list.", err);
        const mockTpas = {
          tpas: [
            { id: "icici_lombard", name: "ICICI Lombard", logo: "🏦", type: "Private", phone: "1800-266-7700" },
            { id: "star_health", name: "Star Health", logo: "⭐", type: "Private", phone: "1800-425-2255" },
            { id: "medi_assist", name: "Medi Assist (TPA)", logo: "🏥", type: "TPA", phone: "1800-425-3030" },
            { id: "paramount_health", name: "Paramount Health (TPA)", logo: "🏥", type: "TPA", phone: "1800-233-8181" },
            { id: "vidal_health", name: "Vidal Health (TPA)", logo: "🏥", type: "TPA", phone: "1800-425-4033" },
          ]
        };
        return new Response(JSON.stringify(mockTpas), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
    }

    // 3. Intercept /chat/providers
    if (url.includes("/chat/providers") && method === "GET") {
      console.log(`[ClaimGPT Interceptor] Mocking LLM Providers`);
      const mockProviders = {
        current: "gemini-1.5-pro",
        available: ["gemini-1.5-pro", "claude-3-5-sonnet", "gpt-4o"],
      };
      return new Response(JSON.stringify(mockProviders), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }

    // 4. Intercept claims requests with static ID
    // Find static claim ID in the URL
    const staticIdMatch = url.match(/00000000-0000-0000-0000-00000000000[1-5]/);
    if (staticIdMatch) {
      const claimId = staticIdMatch[0];
      console.log(`[ClaimGPT Interceptor] Intercepted static claim request (${claimId}): ${url}`);

      // GET /claims/{id}/progress
      if (url.endsWith(`/progress`) || url.includes(`/progress?`)) {
        return new Response(
          JSON.stringify({
            status: "COMPLETED",
            step: "Finalizing Report",
            percentage: 100,
            is_complete: true,
          }),
          { status: 200, headers: { "Content-Type": "application/json" } }
        );
      }

      // GET /claims/{id}/preview
      if (url.endsWith(`/preview`) || url.includes(`/preview?`)) {
        const preview = MOCK_PREVIEW_DATA[claimId];
        return new Response(JSON.stringify(preview), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }

      // GET /claims/{id}/expenses or PUT /claims/{id}/expenses
      if (url.endsWith(`/expenses`)) {
        if (method === "PUT") {
          return new Response(JSON.stringify({ success: true }), { status: 200 });
        }
        const preview = MOCK_PREVIEW_DATA[claimId];
        return new Response(JSON.stringify(preview.expenses), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }

      // GET /claims/{id}/icd-codes or PUT /claims/{id}/icd-codes
      if (url.endsWith(`/icd-codes`)) {
        if (method === "PUT") {
          return new Response(JSON.stringify({ success: true }), { status: 200 });
        }
        const preview = MOCK_PREVIEW_DATA[claimId];
        return new Response(
          JSON.stringify({ icd_codes: preview.icd_codes, cpt_codes: preview.cpt_codes }),
          { status: 200, headers: { "Content-Type": "application/json" } }
        );
      }

      // GET /claims/{id}/fields or PUT /claims/{id}/fields
      if (url.endsWith(`/fields`)) {
        if (method === "PUT") {
          return new Response(JSON.stringify({ success: true }), { status: 200 });
        }
        const preview = MOCK_PREVIEW_DATA[claimId];
        return new Response(JSON.stringify({ parsed_fields: preview.parsed_fields }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }

      // GET /claims/{id}/audit
      if (url.endsWith(`/audit`)) {
        const mockAudit = {
          audit_trail: [
            {
              id: `audit-${claimId}-1`,
              actor: "System OCR",
              action: "DOCUMENT_OCR_PROCESSED",
              metadata: { file_name: "admission_sheet.pdf" },
              created_at: new Date(Date.now() - 3600000 * 2).toISOString(),
            },
            {
              id: `audit-${claimId}-2`,
              actor: "Parser Engine",
              action: "CLINICAL_FIELDS_EXTRACTED",
              metadata: { fields_count: Object.keys(MOCK_PREVIEW_DATA[claimId].parsed_fields).length },
              created_at: new Date(Date.now() - 3600000 * 1.9).toISOString(),
            },
            {
              id: `audit-${claimId}-3`,
              actor: "AI Validator",
              action: "POLICY_RULES_RUN",
              metadata: {
                rules_checked: MOCK_PREVIEW_DATA[claimId].summary.validation_total,
                failures:
                  (MOCK_PREVIEW_DATA[claimId].summary.validation_total || 0) -
                  (MOCK_PREVIEW_DATA[claimId].summary.validation_passed || 0),
              },
              created_at: new Date(Date.now() - 3600000 * 1.8).toISOString(),
            },
          ],
        };
        return new Response(JSON.stringify(mockAudit), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }

      // GET /claims/{id}/tpa-pdf or /irda-pdf
      if (url.includes(`/tpa-pdf`)) {
        console.log(`[ClaimGPT Interceptor] Serving mock TPA PDF for ${claimId}`);
        const pdfBlob = generateMockPdf(claimId, "tpa");
        return new Response(pdfBlob, {
          status: 200,
          headers: { "Content-Type": "application/pdf" },
        });
      }

      if (url.includes(`/irda-pdf`)) {
        console.log(`[ClaimGPT Interceptor] Serving mock IRDA PDF for ${claimId}`);
        const pdfBlob = generateMockPdf(claimId, "irda");
        return new Response(pdfBlob, {
          status: 200,
          headers: { "Content-Type": "application/pdf" },
        });
      }

      // GET /claims/{id}/file
      if (url.includes(`/file`)) {
        let filename = "document.pdf";
        try {
          const urlObj = new URL(url, typeof window !== "undefined" ? window.location.origin : "http://localhost");
          filename = urlObj.searchParams.get("filename") || "document.pdf";
        } catch { /* fallback */ }

        console.log(`[ClaimGPT Interceptor] Serving mock original document PDF (${filename}) for ${claimId}`);
        const mockBlob = generateMockDocumentPdf(claimId, filename);
        return new Response(mockBlob, {
          status: 200,
          headers: { "Content-Type": "application/pdf" },
        });
      }

      // POST /claims/{id}/tpa-action
      if (url.includes(`/tpa-action`)) {
        try {
          const body = JSON.parse(init?.body as string || "{}");
          const action = body.action || "action";
          let newStatus = "COMPLETED";
          if (action === "approve") newStatus = "APPROVED";
          else if (action === "reject") newStatus = "REJECTED";
          else if (action === "send_back") newStatus = "MODIFICATION_REQUESTED";
          else if (action === "send_money") newStatus = "SETTLED";
          else if (action === "request_docs") newStatus = "DOCUMENTS_REQUESTED";

          return new Response(
            JSON.stringify({
              message: `Action '${action}' applied successfully to static claim.`,
              new_status: newStatus,
            }),
            { status: 200, headers: { "Content-Type": "application/json" } }
          );
        } catch {
          return new Response(JSON.stringify({ message: "Action accepted" }), { status: 200 });
        }
      }

      // GET /claims/{id} (Basic metadata fetch for individual claim)
      if (method === "GET") {
        const metadata = MOCK_CLAIMS.find((c) => c.id === claimId);
        return new Response(JSON.stringify(metadata), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }

      // DELETE /claims/{id}
      if (method === "DELETE") {
        return new Response(JSON.stringify({ success: true, message: "Claim deleted" }), { status: 200 });
      }
    }

    // 5. Intercept CHAT requests referring to static claims
    if (url.includes("/chat/") && (url.includes("/stream") || url.includes("/message")) && method === "POST") {
      try {
        const body = JSON.parse(init?.body as string || "{}");
        const claimId = body.claim_id;
        const message = body.message || "";

        if (isStaticClaim(claimId)) {
          console.log(`[ClaimGPT Interceptor] Mocking chatbot response for static claim ${claimId}`);
          const reply = getMockChatResponse(claimId, message);
          const suggestions = getMockChatSuggestions(claimId);

          if (url.includes("/stream")) {
            // Mock streaming SSE response
            const stream = new ReadableStream({
              async start(controller) {
                const encoder = new TextEncoder();
                // Send text chunk by chunk (simulate streaming token by token)
                const chunks = reply.split(" ");
                let currentText = "";
                for (const chunk of chunks) {
                  currentText += (currentText ? " " : "") + chunk;
                  // SSE format: data: {"token": " ", "content": "chunk"}
                  const payload = JSON.stringify({ token: (currentText ? " " : "") + chunk, content: chunk, text: chunk });
                  controller.enqueue(encoder.encode(`data: ${payload}\n`));
                  await new Promise((resolve) => setTimeout(resolve, 35)); // 35ms delay for visual stream effect
                }
                // Send suggestions
                controller.enqueue(encoder.encode(`data: ${JSON.stringify({ suggestions })}\n`));
                controller.enqueue(encoder.encode(`data: [DONE]\n`));
                controller.close();
              },
            });

            return new Response(stream, {
              headers: {
                "Content-Type": "text/event-stream",
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
              },
            });
          } else {
            // Mock regular JSON response
            return new Response(
              JSON.stringify({
                message: reply,
                suggestions,
                field_actions: [],
              }),
              { status: 200, headers: { "Content-Type": "application/json" } }
            );
          }
        }
      } catch (err) {
        console.error("[ClaimGPT Interceptor] Error parsing chat intercept body", err);
      }
    }

    // Fallback: call normal fetch
    return originalFetch(input, init);
  };
}
